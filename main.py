import os, asyncio, logging, json, re
from google import genai
from google.api_core import exceptions # Crítico para capturar el 429
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

# LLAVES DE GEMINI
KEY_PRO = os.getenv("GEMINI_API_KEY_PRO")
KEY_FREE = os.getenv("GEMINI_API_KEY_FREE")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 2. INICIALIZACIÓN DE CLIENTES ---
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Lista de clientes configurados
clients = []
if KEY_PRO: clients.append({"name": "PRO", "client": genai.Client(api_key=KEY_PRO)})
if KEY_FREE: clients.append({"name": "FREE", "client": genai.Client(api_key=KEY_FREE)})

class MoteMovilStates(StatesGroup):
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 3. CEREBRO CON FALLOVER INMEDIATO (v6.6) ---
async def extraer_ia_resiliente(texto, rol):
    """Prueba todas las llaves disponibles antes de rendirse."""
    if not clients:
        logger.error("❌ No hay llaves configuradas.")
        return None

    # Intentamos con cada cliente en la lista
    for entry in clients:
        name = entry["name"]
        c = entry["client"]
        
        try:
            logger.info(f"🛰️ Intentando con llave {name}...")
            # Timeout de 8 segundos por intento para no colgar al usuario
            response = await asyncio.wait_for(
                c.aio.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=f"Extract JSON from: {texto}. Role: {rol}. Fields: [nombre, origen, destino, hora, vehiculo, aporte_bs]. Respond ONLY JSON."
                ),
                timeout=8.0
            )
            
            if response and response.text:
                json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
                if json_match:
                    logger.info(f"✅ Éxito con llave {name}")
                    return json.loads(json_match.group())
                    
        except exceptions.ResourceExhausted:
            logger.warning(f"⚠️ Llave {name} saturada (429). Saltando a la siguiente...")
            continue # Pasa al siguiente cliente en el bucle 'for'
        except Exception as e:
            logger.error(f"⚠️ Error con llave {name}: {e}")
            continue
            
    logger.error("❌ Todas las llaves fallaron o están saturadas.")
    return None

# --- 4. HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🚗 Soy un buen conductor")
    kb.button(text="🚶 Soy pasajero")
    kb.button(text="📖 Como usar el MoteMovil")
    await message.answer("✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def flow_init(message: types.Message, state: FSMContext):
    await state.update_data(rol="conductor" if "conductor" in message.text else "pasajero")
    await state.set_state(MoteMovilStates.registro_ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación:", reply_markup=kb)

@dp.message(MoteMovilStates.registro_ubicacion, F.location)
async def location_rcv(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    data = await state.get_data()
    prompt = "Describe ruta, hora y vehículo:" if data['rol'] == "conductor" else "¿A dónde vas y hora?"
    await message.answer(f"📝 {prompt}", reply_markup=types.ReplyKeyboardRemove())

@dp.message(MoteMovilStates.esperando_datos_ia)
async def final_proc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("⚡ **Conectando con Nodo KyuDan...**")
    
    # El motor ahora agota todas las llaves antes de devolver None
    datos_ia = await extraer_ia_resiliente(message.text, data['rol'])
    
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id, "rol": data['rol'],
        "latitud": data['lat'], "longitud": data['lon'],
        "ruta_raw": message.text, "datos_ia": datos_ia
    }).execute()
    
    await state.clear()
    res_text = "✅ **Ruta Activa**" if datos_ia else "✅ **Ruta Registrada (Modo Manual)**"
    await msg.edit_text(f"{res_text}\n\nYa eres visible para otros socios.", 
                        reply_markup=ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True))

# --- 5. ARRANQUE ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

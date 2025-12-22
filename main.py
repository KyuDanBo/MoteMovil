import os, asyncio, logging, json, re
from google import genai
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN E IDENTIDAD ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

# LLAVES DE GEMINI
KEY_PRO = os.getenv("GEMINI_API_KEY_PRO")
KEY_FREE = os.getenv("GEMINI_API_KEY_FREE")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 2. INICIALIZACIÓN DE SERVICIOS ---
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    logger.info("✅ Servicios base (Bot/Supabase) listos.")
except Exception as e:
    logger.error(f"❌ Error al iniciar servicios base: {e}")

# Inicialización de Clientes Gemini
clients = []
if KEY_PRO: clients.append(genai.Client(api_key=KEY_PRO))
if KEY_FREE: clients.append(genai.Client(api_key=KEY_FREE))
current_idx = 0

class MoteMovilStates(StatesGroup):
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 3. LOGICA DE IA (CON FALLBACK) ---
async def extraer_ia(texto, rol):
    global current_idx
    if not clients:
        return None
    try:
        client = clients[current_idx]
        # Usamos 2.0-flash que es el más estable en 2025 para esta librería
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Extrae JSON de transporte: {texto}. Rol: {rol}"
        )
        if response and response.text:
            json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
            return json.loads(json_match.group()) if json_match else None
    except Exception as e:
        logger.warning(f"⚠️ Fallo en cliente IA #{current_idx}: {e}")
        current_idx = (current_idx + 1) % len(clients)
    return None

# --- 4. HANDLERS PRINCIPALES ---
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🚗 Soy un buen conductor")
    kb.button(text="🚶 Soy pasajero")
    kb.button(text="📖 Como usar el MoteMovil")
    await message.answer("✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n¿Cómo participarás hoy?", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def rol_inicio(message: types.Message, state: FSMContext):
    await state.update_data(rol="conductor" if "conductor" in message.text else "pasajero")
    await state.set_state(MoteMovilStates.registro_ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación:", reply_markup=kb)

@dp.message(MoteMovilStates.registro_ubicacion, F.location)
async def location_receive(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    data = await state.get_data()
    prompt = "Describe tu ruta, hora y vehículo:" if data['rol'] == "conductor" else "¿A dónde vas y hasta qué hora?"
    await message.answer(f"📝 {prompt}", reply_markup=types.ReplyKeyboardRemove())

@dp.message(MoteMovilStates.esperando_datos_ia)
async def process_ia(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg = await message.answer("⚡ Procesando...")
    
    # Intento de IA
    datos_ia = await extraer_ia(message.text, data['rol'])
    
    # Registro en Supabase
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id, "rol": data['rol'],
        "latitud": data['lat'], "longitud": data['lon'],
        "ruta_raw": message.text, "datos_ia": datos_ia
    }).execute()
    
    await state.clear()
    await msg.edit_text("✅ **¡Ruta Activa!**\n\nTu trayecto está registrado en el búnker.", 
                        reply_markup=ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True))

# --- 5. SERVIDOR DE SALUD (RENDER) ---
async def handle(request):
    return web.Response(text="MOTEMOVIL LIVE")

async def main():
    # Iniciamos el servidor web PRIMERO para que Render no mate el proceso
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"🌐 Servidor de salud iniciado en puerto {PORT}")

    # Iniciamos el bot
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

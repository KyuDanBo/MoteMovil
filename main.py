import os, asyncio, logging, json, re
from google import genai #
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN E IDENTIDAD ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") #
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# Inicialización del Cliente Asíncrono (CRÍTICO para evitar cuelgues)
#
client = genai.Client(api_key=GEMINI_API_KEY)
# Nota: Si gemini-2.5-flash da error, el sistema usará gemini-2.0-flash como respaldo
MODEL_NAME = "gemini-2.0-flash" 

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 2. CEREBRO GEMINI ASÍNCRONO (PROTOCOLO KYUDAN) ---
async def extraer_ia_gemini_async(texto, rol="conductor"):
    """Usa el motor aio para que la solicitud no se pierda."""
    try:
        prompt = (
            f"Contexto: MOTEMOVIL de EcoBanco. Tarea: Extraer JSON puro.\n"
            f"Texto: '{texto}'\n"
            f"Campos: [nombre, origen, destino, hora, vehiculo, aporte_bs].\n"
            f"Responde SOLO el JSON."
        )
        
        # Uso de client.aio para evitar el bloqueo en Render
        #
        response = await client.aio.models.generate_content(
            model=MODEL_NAME,
            contents=prompt
        )
        
        if response and response.text:
            clean_text = re.sub(r'```json|```', '', response.text).strip()
            json_match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            return json.loads(json_match.group()) if json_match else None
        return None
    except Exception as e:
        logging.error(f"⚠️ Fallo de conexión con Gemini: {e}")
        return None

# --- 3. HANDLERS DE OPERACIÓN ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🚗 Soy un buen conductor")
    kb.button(text="🚶 Soy pasajero")
    kb.button(text="📖 Como usar el MoteMovil")
    await message.answer(
        "✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n"
        "Sistema de IA Asíncrona activado.\n"
        "¿Cómo participarás hoy?",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def iniciar_flujo(message: types.Message, state: FSMContext):
    await state.update_data(rol="conductor" if "conductor" in message.text else "pasajero")
    await state.set_state(MoteMovilStates.registro_ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para el match:", reply_markup=kb)

@dp.message(MoteMovilStates.registro_ubicacion, F.location)
async def recibir_ubicacion(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    data = await state.get_data()
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    
    msg = "🚗 **Datos del Conductor**\nDime: Nombre, ruta, hora, asientos, aporte y vehículo." if data['rol'] == "conductor" else "🚶 **Datos del Pasajero**\n¿A dónde vas y cuál es tu hora límite?"
    await message.answer(msg, reply_markup=types.ReplyKeyboardRemove())

@dp.message(MoteMovilStates.esperando_datos_ia)
async def procesar_ia_final(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    msg_espera = await message.answer("⚡ **Analizando con Gemini 2.0 Flash...**")
    
    # Intento de extracción con timeout para no colgar el bot
    try:
        datos_ia = await asyncio.wait_for(
            extraer_ia_gemini_async(message.text, user_data['rol']), 
            timeout=15.0
        )
    except asyncio.TimeoutError:
        datos_ia = None
        logging.error("⏳ Tiempo de espera agotado para Gemini.")

    # Registro en Supabase
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id,
        "rol": user_data['rol'],
        "latitud": user_data['lat'],
        "longitud": user_data['lon'],
        "ruta_raw": message.text,
        "datos_ia": datos_ia,
        "estado": "activo"
    }).execute()

    await state.clear()
    await msg_espera.edit_text(
        "✅ **¡Recorrido Activado!**\n\nTu ruta está en el Libro Mayor de EcoBanco.\n"
        "Te avisaremos al detectar un match.",
        reply_markup=ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True)
    )

# --- 4. ARRANQUE (Render) ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start() #
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

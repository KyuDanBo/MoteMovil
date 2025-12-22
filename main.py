import os, asyncio, logging, math, json, re
import google.generativeai as genai
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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

# Verificación de Seguridad Crítica
if not GEMINI_API_KEY:
    logging.error("❌ ERROR CRÍTICO: GEMINI_API_KEY no encontrada en Environment.")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 2. CEREBRO GEMINI (MODO ASÍNCRONO NATIVO) ---
async def extraer_ia_gemini(texto, rol="conductor"):
    """Versión optimizada para evitar bloqueos en Render."""
    try:
        logging.info(f"📡 Enviando solicitud a Gemini para {rol}...")
        prompt = (
            f"Actúa como el motor de MOTEMOVIL. Extrae los datos en JSON puro de: '{texto}'. "
            f"Campos para {rol}: [nombre, origen, destino, hora, vehiculo, aporte_bs]. "
            f"Respuesta: SOLO el JSON, sin texto extra."
        )
        
        # Usamos la versión asíncrona nativa de Gemini
        response = await model.generate_content_async(prompt)
        
        if not response or not response.text:
            logging.warning("⚠️ Gemini no devolvió texto (posible bloqueo de seguridad o cuota).")
            return None
            
        logging.info(f"📥 Respuesta de Gemini recibida con éxito.")
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        return json.loads(json_match.group()) if json_match else None

    except Exception as e:
        logging.error(f"💥 Error en el motor Gemini: {e}")
        return None

# --- 3. HANDLERS (FLUJO ESTABLE) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardBuilder()
    kb.button(text="🚗 Soy un buen conductor")
    kb.button(text="🚶 Soy pasajero")
    kb.button(text="📖 Como usar el MoteMovil")
    await message.answer("✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n¿Cómo participarás hoy?", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def iniciar_flujo(message: types.Message, state: FSMContext):
    await state.update_data(rol="conductor" if "conductor" in message.text else "pasajero")
    await state.set_state(MoteMovilStates.registro_ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir mi ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para el match:", reply_markup=kb)

@dp.message(MoteMovilStates.registro_ubicacion, F.location)
async def recibir_ubicacion(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    data = await state.get_data()
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    
    prompt = "🚗 Describe: Nombre, Ruta, Hora, Asientos, Aporte y datos del Vehículo." if data['rol'] == "conductor" else "🚶 ¿A dónde vas y cuál es tu hora límite?"
    await message.answer(prompt, reply_markup=types.ReplyKeyboardRemove())

@dp.message(MoteMovilStates.esperando_datos_ia)
async def procesar_con_gemini(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    msg_espera = await message.answer("⚡ **IA Gemini analizando tu ruta...**")
    
    # Intento de extracción IA con timeout de seguridad
    try:
        datos_ia = await asyncio.wait_for(extraer_ia_gemini(message.text, user_data['rol']), timeout=15.0)
    except asyncio.TimeoutError:
        logging.error("⏳ Timeout: Gemini tardó demasiado.")
        datos_ia = None

    # Registro resiliente en Supabase
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
        "✅ **¡Recorrido Activado!**\n\n"
        "Ya eres visible en el Libro Mayor de EcoBanco.\n"
        "Te avisaremos apenas encontremos un match.",
        reply_markup=ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True)
    )

# --- 4. ARRANQUE (Render) ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") # Nueva Llave Maestra
PORT = int(os.getenv("PORT", 10000))

# Configuración de Google Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    esperando_kyc = State()
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 2. CEREBRO GEMINI (EXTRACCIÓN DE PRECISIÓN) ---
async def extraer_ia_gemini(texto, rol="conductor"):
    """Usa Gemini para convertir lenguaje natural en datos para el Libro Mayor."""
    try:
        prompt = (
            f"Actúa como el procesador de MOTEMOVIL. Extrae los siguientes datos en formato JSON puro "
            f"del texto: '{texto}'. "
            f"Si es conductor: [nombre, origen, destino, paradas, asientos, aporte_bs, vehiculo, hora]. "
            f"Si es pasajero: [nombre, origen, destino, hora_limite]. "
            f"IMPORTANTE: Devuelve SOLO el JSON, nada de texto extra."
        )
        response = await asyncio.to_thread(model.generate_content, prompt)
        
        # Limpieza de la respuesta para obtener el JSON
        raw_text = response.text
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return None
    except Exception as e:
        logging.error(f"⚠️ Fallo Crítico Gemini: {e}")
        return None

# --- 3. HANDLERS DE OPERACIÓN (ESTABLE) ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Registro/Actualización de Perfil
    supabase.table("perfiles").upsert({"user_id": message.from_user.id, "nombre": message.from_user.full_name}).execute()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="🚗 Soy un buen conductor")
    kb.button(text="🚶 Soy pasajero")
    kb.button(text="📖 Como usar el MoteMovil")
    await message.answer(
        "✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n"
        "Selecciona tu rol para iniciar el trayecto:",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def iniciar_flujo(message: types.Message, state: FSMContext):
    rol = "conductor" if "conductor" in message.text else "pasajero"
    await state.update_data(rol=rol)
    await state.set_state(MoteMovilStates.registro_ubicacion)
    
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir mi ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Para conectar con otros socios, comparte tu ubicación actual:", reply_markup=kb)

@dp.message(MoteMovilStates.registro_ubicacion, F.location)
async def recibir_ubicacion(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    data = await state.get_data()
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    
    if data['rol'] == "conductor":
        texto = "🚗 **Datos del Recorrido**\nDime: Nombre, Ruta, Hora, Asientos, Aporte y **datos de tu vehículo**."
    else:
        texto = "🚶 **Datos del Pasajero**\n¿A dónde vas y cuál es tu hora límite de salida?"
    
    await message.answer(texto, reply_markup=types.ReplyKeyboardRemove())

@dp.message(MoteMovilStates.esperando_datos_ia)
async def procesar_con_gemini(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    msg_espera = await message.answer("⚡ **IA Gemini procesando...**")
    
    datos_ia = await extraer_ia_gemini(message.text, user_data['rol'])
    
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
        "✅ **¡Recorrido Activado en MOTEMOVIL!**\n\n"
        "La IA ha registrado tu ruta con éxito.\n"
        "Te avisaremos apenas encontremos un match compatible.",
        reply_markup=ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True)
    )

# --- 4. SERVIDOR DE SALUD (Render) ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

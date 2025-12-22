import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from supabase import create_client
from aiohttp import web

# --- 1. IDENTIDAD KYUDAN ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    esperando_ubicacion = State()
    esperando_datos_ia = State()

# --- 2. CONSTRUCCIÓN DE INTERFAZ (BOTONES EXACTOS) ---
def get_main_kb():
    builder = ReplyKeyboardBuilder()
    # Los textos deben coincidir EXACTAMENTE con los handlers
    builder.button(text="🚗 Soy un buen conductor")
    builder.button(text="🚶 Soy pasajero")
    builder.button(text="📖 Como usar el MoteMovil")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_location_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📍 Compartir mi ubicación actual", request_location=True)
    builder.button(text="❌ Cancelar")
    return builder.as_markup(resize_keyboard=True)

# --- 3. VALIDACIÓN DE BLOQUEO ---
async def tiene_viaje_activo(user_id):
    res = supabase.table("viajes").select("*").eq("usuario_id", user_id).in_("estado", ["activo", "en_progreso"]).execute()
    return len(res.data) > 0

# --- 4. HANDLERS PRINCIPALES ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n"
        "\"Cambiando de mentalidad para conseguir prosperidad\"\n\n"
        "Selecciona tu rol para iniciar el trayecto:",
        reply_markup=get_main_kb(), parse_mode="Markdown"
    )

# INICIO DE FLUJO: CONDUCTOR / PASAJERO
@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def iniciar_flujo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    rol = "conductor" if "conductor" in message.text else "pasajero"
    
    if await tiene_viaje_activo(user_id):
        aviso = "⚠️ Tienes conexiones abiertas. Finaliza tu recorrido." if rol == "conductor" else "⚠️ No has finalizado tu recorrido anterior."
        await message.answer(aviso)
        return

    await state.update_data(rol=rol)
    await state.set_state(MoteMovilStates.esperando_ubicacion)
    await message.answer(
        f"📍 Para un mejor match, por favor comparte tu ubicación actual.\n\n"
        "Esto nos permite conectar personas en la misma zona sin depender solo de nombres de calles.",
        reply_markup=get_location_kb()
    )

# CAPTURA DE UBICACIÓN
@dp.message(MoteMovilStates.esperando_ubicacion, F.location)
async def recibir_ubicacion(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    data = await state.get_data()
    
    await state.update_data(lat=lat, lon=lon)
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    
    if data['rol'] == "conductor":
        prompt = ("🚗 **Datos del Conductor y Vehículo**\n\n"
                  "Dime: Nombre, Ruta (inicio y fin), Hora, Asientos, Aporte y **modelo/placa de tu vehículo**.")
    else:
        prompt = "🚶 **Datos del Pasajero**\n\n¿A dónde vas y cuál es tu hora límite de salida?"
        
    await message.answer(prompt, reply_markup=types.ReplyKeyboardRemove())

# PROCESAMIENTO FINAL (IA + SUPABASE)
@dp.message(MoteMovilStates.esperando_datos_ia)
async def procesar_datos_ia(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    msg_espera = await message.answer("🤖 IA KyuDan procesando datos...")
    
    # Aquí se integraría la extracción de IA Mistral
    # Guardamos en Supabase incluyendo coordenadas y datos de vehículo
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id,
        "rol": user_data['rol'],
        "latitud": user_data['lat'],
        "longitud": user_data['lon'],
        "ruta_raw": message.text,
        "estado": "activo"
    }).execute()

    await state.clear()
    await msg_espera.edit_text(
        "✅ **¡Registro Exitoso!**\n\n"
        "Tu ubicación y datos han sido guardados en el búnker.\n"
        "Te avisaremos cuando haya un match compatible.",
        reply_markup=get_main_kb()
    )

# --- 5. ARRANQUE ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL Live"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

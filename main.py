import os, asyncio, logging, math
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- 2. ESTADOS ---
class FormConductor(StatesGroup):
    ubicacion = State()
    nombre = State()
    ruta = State()
    asientos = State()
    aporte = State()
    hora = State()
    vehiculo = State()

# --- 3. LÓGICA DE CONTROL ---
def get_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🚗 Soy un buen conductor")
    builder.button(text="🚶 Soy pasajero")
    builder.button(text="📖 Como usar el MoteMovil")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- 4. FLUJO CONDUCTOR (CORREGIDO) ---
@dp.message(F.text == "🚗 Soy un buen conductor")
async def cond_start(message: types.Message, state: FSMContext):
    await state.set_state(FormConductor.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("✨ **Iniciando registro de conductor.**\nComparte tu ubicación para el match:", reply_markup=kb)

@dp.message(FormConductor.ubicacion, F.location)
async def cond_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(FormConductor.nombre)
    await message.answer("📝 ¿Tu nombre?", reply_markup=types.ReplyKeyboardRemove())

@dp.message(FormConductor.nombre)
async def cond_nom(message: types.Message, state: FSMContext):
    await state.update_data(nombre=message.text)
    await state.set_state(FormConductor.ruta)
    await message.answer("🛣️ ¿Cuál es tu ruta? (Ej: Ceja - Pérez)")

@dp.message(FormConductor.ruta)
async def cond_ruta(message: types.Message, state: FSMContext):
    await state.update_data(ruta=message.text)
    await state.set_state(FormConductor.asientos)
    await message.answer("💺 ¿Cuántos asientos libres?")

@dp.message(FormConductor.asientos)
async def cond_as(message: types.Message, state: FSMContext):
    await state.update_data(asientos=message.text)
    await state.set_state(FormConductor.aporte)
    await message.answer("💰 ¿Aporte sugerido en Bs?")

@dp.message(FormConductor.aporte)
async def cond_ap(message: types.Message, state: FSMContext):
    await state.update_data(aporte=message.text)
    await state.set_state(FormConductor.hora)
    await message.answer("⏰ ¿Hora de salida?")

@dp.message(FormConductor.hora)
async def cond_hora(message: types.Message, state: FSMContext):
    await state.update_data(hora=message.text)
    await state.set_state(FormConductor.vehiculo)
    await message.answer("🚘 ¿Datos de tu vehículo? (Modelo/Color)")

@dp.message(FormConductor.vehiculo)
async def cond_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    msg_wait = await message.answer("💾 Guardando en el búnker de EcoBanco...")
    
    try:
        # Sincronizamos con las columnas REALES de su Supabase
        supabase.table("viajes").insert({
            "usuario_id": message.from_user.id,
            "rol": "conductor",
            "latitud": data['lat'],
            "longitud": data['lon'],
            "ruta_raw": data['ruta'],
            "estado": "activo",
            "datos_ia": { # Usamos la columna que ya existe en su SQL
                "nombre": data['nombre'],
                "asientos": data['asientos'],
                "aporte": data['aporte'],
                "hora": data['hora'],
                "vehiculo": message.text
            }
        }).execute()
        
        await state.clear()
        kb = ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True)
        await msg_wait.edit_text("✅ **¡Registro Exitoso!**\nYa eres visible para los pasajeros.", reply_markup=kb)
        
    except Exception as e:
        logging.error(f"❌ Error en Supabase: {e}")
        await msg_wait.edit_text(f"⚠️ **Error al guardar:** {e}\n\nPor favor, verifica que la tabla 'viajes' tenga la columna 'datos_ia'.")

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

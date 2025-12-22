import os, asyncio, logging, math
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicialización segura
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
except Exception as e:
    logger.error(f"❌ Error de inicio: {e}")

class FormConductor(StatesGroup):
    pasos = State() # Simplificamos a un solo flujo de recolección

class FormPasajero(StatesGroup):
    ubicacion = State()

# --- 2. TECLADOS ---
def get_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🚗 Soy un buen conductor")
    builder.button(text="🚶 Soy pasajero")
    builder.button(text="📖 Como usar el MoteMovil")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_driver_control_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🏁 Terminar viaje")
    builder.button(text="❌ Cancelar viaje")
    builder.button(text="📋 Mis Motes")
    builder.adjust(2, 1)
    return builder.as_markup(resize_keyboard=True)

# --- 3. LÓGICA DE MATCHING ---
def calcular_distancia(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- 4. HANDLERS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥", reply_markup=get_main_kb())

# FLUJO CONDUCTOR (SECUENCIAL RÁPIDO)
@dp.message(F.text == "🚗 Soy un buen conductor")
async def cond_init(message: types.Message, state: FSMContext):
    await state.set_state(FormConductor.pasos)
    await state.update_data(step=1)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para iniciar:", reply_markup=kb)

@dp.message(FormConductor.pasos, F.location)
async def cond_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude, step=2)
    await message.answer("📝 ¿Cuál es tu nombre?", reply_markup=types.ReplyKeyboardRemove())

@dp.message(FormConductor.pasos)
async def cond_steps(message: types.Message, state: FSMContext):
    data = await state.get_data()
    step = data.get("step")

    if step == 2:
        await state.update_data(nombre=message.text, step=3)
        await message.answer("🛣️ ¿Cuál es tu ruta? (Ej: Ceja - Pérez)")
    elif step == 3:
        await state.update_data(ruta=message.text, step=4)
        await message.answer("💺 ¿Asientos libres y hora de salida?")
    elif step == 4:
        await state.update_data(info=message.text, step=5)
        await message.answer("🚘 Datos de tu vehículo (Modelo/Color):")
    elif step == 5:
        # GUARDAR EN SUPABASE
        try:
            supabase.table("viajes").insert({
                "usuario_id": message.from_user.id, "rol": "conductor",
                "latitud": data['lat'], "longitud": data['lon'],
                "ruta_raw": data['ruta'], "estado": "activo",
                "detalles": {"nombre": data['nombre'], "info": data['info'], "vehiculo": message.text}
            }).execute()
            await state.clear()
            await message.answer("✅ **Registro Exitoso**", reply_markup=get_driver_control_kb())
        except Exception as e:
            await message.answer(f"⚠️ Error: {e}")

# FLUJO PASAJERO (MATCHING SEGURO)
@dp.message(F.text == "🚶 Soy pasajero")
async def pas_init(message: types.Message, state: FSMContext):
    await state.set_state(FormPasajero.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para buscar conductores:", reply_markup=kb)

@dp.message(FormPasajero.ubicacion, F.location)
async def pas_match(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    await message.answer("🔍 Buscando conductores a 1km...")
    
    res = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
    matches = [c for c in res.data if calcular_distancia(lat, lon, c['latitud'], c['longitud']) <= 1000]
    
    if not matches:
        await message.answer("🔍 No hay conductores cerca ahora.", reply_markup=get_main_kb())
    else:
        text = "✨ **Conductores cerca:**\n\n"
        for v in matches:
            d = v.get('detalles', {})
            text += f"🚗 {d.get('nombre')} | {d.get('info')}\n"
        await message.answer(text, reply_markup=get_main_kb())
    await state.clear()

# BOTONES DE CONTROL
@dp.message(F.text.in_(["🏁 Terminar viaje", "❌ Cancelar viaje"]))
async def control_trip(message: types.Message):
    estado = "finalizado" if "Terminar" in message.text else "cancelado"
    supabase.table("viajes").update({"estado": estado}).eq("usuario_id", message.from_user.id).execute()
    await message.answer(f"✨ Trayecto {estado}.", reply_markup=get_main_kb())

# --- 5. ARRANQUE ---
async def handle(request): return web.Response(text="LIVE")

async def main():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    # Arrancamos servidor de salud PRIMERO
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    # Arrancamos el bot
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

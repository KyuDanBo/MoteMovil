import os, asyncio, logging, math
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
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- 2. MÁQUINA DE ESTADOS (FLUJO SECUENCIAL) ---
class FormConductor(StatesGroup):
    ubicacion = State()
    nombre = State()
    ruta = State()
    asientos = State()
    aporte = State()
    hora = State()
    vehiculo = State()

class FormPasajero(StatesGroup):
    ubicacion = State()

# --- 3. HERRAMIENTAS TÉCNICAS ---
def calcular_distancia(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def get_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🚗 Soy un buen conductor")
    builder.button(text="🚶 Soy pasajero")
    builder.button(text="📖 Como usar el MoteMovil")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

# --- 4. HANDLERS DE FLUJO ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n"
        "Sistema operativo de movilidad solidaria.\n"
        "¿Cómo participarás hoy?", reply_markup=get_main_kb())

# --- FLUJO CONDUCTOR ---
@dp.message(F.text == "🚗 Soy un buen conductor")
async def cond_1(message: types.Message, state: FSMContext):
    await state.set_state(FormConductor.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para el inicio del viaje:", reply_markup=kb)

@dp.message(FormConductor.ubicacion, F.location)
async def cond_2(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(FormConductor.nombre)
    await message.answer("📝 ¿Cuál es tu nombre?", reply_markup=types.ReplyKeyboardRemove())

@dp.message(FormConductor.nombre)
async def cond_3(message: types.Message, state: FSMContext):
    await state.update_data(nombre=message.text)
    await state.set_state(FormConductor.ruta)
    await message.answer("🛣️ Describe tu ruta (Ej: Ceja - Ballivian - Rio Seco):")

@dp.message(FormConductor.ruta)
async def cond_4(message: types.Message, state: FSMContext):
    await state.update_data(ruta=message.text)
    await state.set_state(FormConductor.asientos)
    await message.answer("💺 ¿Cuántos asientos tienes?")

@dp.message(FormConductor.asientos)
async def cond_5(message: types.Message, state: FSMContext):
    await state.update_data(asientos=message.text)
    await state.set_state(FormConductor.aporte)
    await message.answer("💰 ¿Aporte sugerido en Bs?")

@dp.message(FormConductor.aporte)
async def cond_6(message: types.Message, state: FSMContext):
    await state.update_data(aporte=message.text)
    await state.set_state(FormConductor.hora)
    await message.answer("⏰ ¿A qué hora sales?")

@dp.message(FormConductor.hora)
async def cond_7(message: types.Message, state: FSMContext):
    await state.update_data(hora=message.text)
    await state.set_state(FormConductor.vehiculo)
    await message.answer("🚘 Datos de tu vehículo (Modelo/Color/Placa):")

@dp.message(FormConductor.vehiculo)
async def cond_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        supabase.table("viajes").insert({
            "usuario_id": message.from_user.id, "rol": "conductor",
            "latitud": data['lat'], "longitud": data['lon'],
            "ruta_raw": data['ruta'], "estado": "activo",
            "detalles": {
                "nombre": data['nombre'], "asientos": data['asientos'],
                "aporte": data['aporte'], "hora": data['hora'], "vehiculo": message.text
            }
        }).execute()
        await state.clear()
        kb = ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True)
        await message.answer("✅ **¡Registro Exitoso!**\nTu ruta es visible para pasajeros a 1km.", reply_markup=kb)
    except Exception as e:
        logger.error(f"Error: {e}")
        await message.answer("⚠️ Error al guardar. Reintenta.")

# --- FLUJO PASAJERO ---
@dp.message(F.text == "🚶 Soy pasajero")
async def pas_1(message: types.Message, state: FSMContext):
    await state.set_state(FormPasajero.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir mi ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para buscar conductores cerca:", reply_markup=kb)

@dp.message(FormPasajero.ubicacion, F.location)
async def pas_match(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    res = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
    matches = [c for c in res.data if calcular_distancia(lat, lon, c['latitud'], c['longitud']) <= 1000]
    
    if not matches:
        await message.answer("🔍 No hay conductores a 1km ahora.", reply_markup=get_main_kb())
    else:
        lista = "\n".join([f"🚗 {v['detalles']['nombre']} | ⏰ {v['detalles']['hora']} | 💰 {v['detalles']['aporte']}Bs" for v in matches])
        await message.answer(f"✨ **Conductores cerca:**\n\n{lista}")
    await state.clear()

# --- 5. ARRANQUE DEL SISTEMA ---
async def handle(request):
    return web.Response(text="MOTEMOVIL NUCLEO V8.0 LIVE")

async def main():
    # Iniciamos Servidor de Salud para Render
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    # Iniciamos Polling del Bot
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

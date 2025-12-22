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

# --- 2. ESTADOS DEL CUESTIONARIO (FSM) ---
class FormConductor(StatesGroup):
    ubicacion = State()
    nombre = State()
    ruta_puntos = State() # Origen -> Paradas -> Destino
    asientos = State()
    aporte = State()
    hora = State()
    vehiculo = State()

class FormPasajero(StatesGroup):
    ubicacion = State()
    nombre = State()
    destino = State()
    hora_limite = State()

# --- 3. FUNCIONES DE APOYO ---
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

# --- 4. FLUJO DE INICIO ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n"
        "Sistema de movilidad solidaria activado e instantáneo.\n"
        "¿Cómo participarás hoy?", reply_markup=get_main_kb())

# --- 5. FLUJO SECUENCIAL: CONDUCTOR ---
@dp.message(F.text == "🚗 Soy un buen conductor")
async def cond_step1(message: types.Message, state: FSMContext):
    await state.set_state(FormConductor.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación actual", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Para iniciar, comparte tu ubicación actual:", reply_markup=kb)

@dp.message(FormConductor.ubicacion, F.location)
async def cond_step2(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(FormConductor.nombre)
    await message.answer("📝 ¿Cuál es tu nombre?", reply_markup=types.ReplyKeyboardRemove())

@dp.message(FormConductor.nombre)
async def cond_step3(message: types.Message, state: FSMContext):
    await state.update_data(nombre=message.text)
    await state.set_state(FormConductor.ruta_puntos)
    await message.answer("🛣️ Describe tu ruta (Ej: Ceja - Ballivian - Rio Seco):")

@dp.message(FormConductor.ruta_puntos)
async def cond_step4(message: types.Message, state: FSMContext):
    await state.update_data(ruta=message.text)
    await state.set_state(FormConductor.asientos)
    await message.answer("💺 ¿Cuántos asientos tienes disponibles?")

@dp.message(FormConductor.asientos)
async def cond_step5(message: types.Message, state: FSMContext):
    await state.update_data(asientos=message.text)
    await state.set_state(FormConductor.aporte)
    await message.answer("💰 ¿Cuál es el aporte sugerido en Bs?")

@dp.message(FormConductor.aporte)
async def cond_step6(message: types.Message, state: FSMContext):
    await state.update_data(aporte=message.text)
    await state.set_state(FormConductor.hora)
    await message.answer("⏰ ¿A qué hora sales? (Ej: 08:30)")

@dp.message(FormConductor.hora)
async def cond_step7(message: types.Message, state: FSMContext):
    await state.update_data(hora=message.text)
    await state.set_state(FormConductor.vehiculo)
    await message.answer("🚘 Datos de tu vehículo (Modelo y Color):")

@dp.message(FormConductor.vehiculo)
async def cond_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    # Guardado estructurado en Supabase
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
    await message.answer("✅ **¡Ruta publicada con éxito!**\nYa eres visible para los pasajeros cerca.", reply_markup=kb)

# --- 6. FLUJO SECUENCIAL: PASAJERO ---
@dp.message(F.text == "🚶 Soy pasajero")
async def pas_step1(message: types.Message, state: FSMContext):
    await state.set_state(FormPasajero.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir ubicación actual", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para buscar conductores:", reply_markup=kb)

@dp.message(FormPasajero.ubicacion, F.location)
async def pas_step2(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    await state.update_data(lat=lat, lon=lon)
    
    # Búsqueda inmediata de Match por cercanía (1km)
    res = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
    matches = [c for c in res.data if calcular_distancia(lat, lon, c['latitud'], c['longitud']) <= 1000]
    
    if not matches:
        await message.answer("🔍 No hay conductores a 1km de tu posición. Te avisaremos si alguien se conecta.", reply_markup=get_main_kb())
        await state.clear()
    else:
        lista = "\n".join([f"🚗 {c['detalles']['nombre']} - {c['detalles']['hora']} - {c['detalles']['aporte']} Bs" for c in matches])
        await message.answer(f"✨ **Conductores encontrados cerca:**\n\n{lista}\n\nEscribe tu destino para concretar el match:")
        await state.set_state(FormPasajero.destino)

@dp.message(FormPasajero.destino)
async def pas_final(message: types.Message, state: FSMContext):
    await message.answer("✅ **Solicitud registrada.**\nEstamos notificando a los conductores compatibles.", reply_markup=get_main_kb())
    await state.clear()

# --- 7. ARRANQUE ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

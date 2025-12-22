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
logger = logging.getLogger(__name__)

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

class FormPasajero(StatesGroup):
    ubicacion = State()

# --- 3. TECLADOS ---
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
    builder.adjust(2, 1) # Dos botones arriba, uno abajo
    return builder.as_markup(resize_keyboard=True)

# --- 4. UTILIDADES ---
def calcular_distancia(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- 5. FLUJO CONDUCTOR ---
@dp.message(F.text == "🚗 Soy un buen conductor")
async def cond_start(message: types.Message, state: FSMContext):
    await state.set_state(FormConductor.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir mi ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para iniciar el viaje:", reply_markup=kb)

@dp.message(FormConductor.ubicacion, F.location)
async def cond_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(FormConductor.nombre)
    await message.answer("📝 ¿Tu nombre?", reply_markup=types.ReplyKeyboardRemove())

# ... (Pasos intermedios omitidos para brevedad, asumiendo que funcionan bien)
@dp.message(FormConductor.nombre)
async def cond_nom(message: types.Message, state: FSMContext):
    await state.update_data(nombre=message.text); await state.set_state(FormConductor.ruta)
    await message.answer("🛣️ ¿Cuál es tu ruta?")

@dp.message(FormConductor.ruta)
async def cond_rut(message: types.Message, state: FSMContext):
    await state.update_data(ruta=message.text); await state.set_state(FormConductor.asientos)
    await message.answer("💺 ¿Asientos libres?")

@dp.message(FormConductor.asientos)
async def cond_as(message: types.Message, state: FSMContext):
    await state.update_data(asientos=message.text); await state.set_state(FormConductor.aporte)
    await message.answer("💰 ¿Aporte en Bs?")

@dp.message(FormConductor.aporte)
async def cond_ap(message: types.Message, state: FSMContext):
    await state.update_data(aporte=message.text); await state.set_state(FormConductor.hora)
    await message.answer("⏰ ¿Hora de salida?")

@dp.message(FormConductor.hora)
async def cond_hor(message: types.Message, state: FSMContext):
    await state.update_data(hora=message.text); await state.set_state(FormConductor.vehiculo)
    await message.answer("🚘 ¿Datos de tu vehículo?")

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
        # Panel de control solicitado por el CEO
        await message.answer("✅ **¡Registro Exitoso!**\nYa eres visible para los pasajeros.\nUsa los botones de abajo para controlar tu viaje.", 
                             reply_markup=get_driver_control_kb())
    except Exception as e:
        logger.error(f"Error DB: {e}")
        await message.answer("⚠️ Error al guardar.")

# --- 6. FLUJO PASAJERO (CORRECCIÓN DE ESTANCAMIENTO) ---
@dp.message(F.text == "🚶 Soy pasajero")
async def pas_start(message: types.Message, state: FSMContext):
    await state.set_state(FormPasajero.ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir mi ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para buscar conductores cerca:", reply_markup=kb)

@dp.message(FormPasajero.ubicacion, F.location)
async def pas_match(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    await message.answer("🔍 Buscando conductores a menos de 1km...")
    
    try:
        # Consulta segura
        res = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
        
        matches = []
        for c in res.data:
            dist = calcular_distancia(lat, lon, c['latitud'], c['longitud'])
            if dist <= 1000:
                matches.append(c)
        
        if not matches:
            await message.answer("🔍 No hay conductores activos en tu radio de 1km ahora.", reply_markup=get_main_kb())
        else:
            text = "✨ **Conductores encontrados:**\n\n"
            for v in matches:
                # Acceso seguro a los datos para evitar estancamiento
                d = v.get('detalles', {})
                nombre = d.get('nombre', 'Socio')
                hora = d.get('hora', '--:--')
                aporte = d.get('aporte', '0')
                text += f"🚗 {nombre} | ⏰ {hora} | 💰 {aporte}Bs\n"
            
            await message.answer(text, reply_markup=get_main_kb())
            
    except Exception as e:
        logger.error(f"Error en Match: {e}")
        await message.answer("⚠️ Hubo un problema al consultar el Libro Mayor.")
    
    await state.clear()

# --- 7. HANDLERS DE BOTONES DE CONTROL ---
@dp.message(F.text == "🏁 Terminar viaje")
async def finish_trip(message: types.Message):
    supabase.table("viajes").update({"estado": "finalizado"}).eq("usuario_id", message.from_user.id).execute()
    await message.answer("✨ Trayecto finalizado con éxito.", reply_markup=get_main_kb())

@dp.message(F.text == "❌ Cancelar viaje")
async def cancel_trip(message: types.Message):
    supabase.table("viajes").update({"estado": "cancelado"}).eq("usuario_id", message.from_user.id).execute()
    await message.answer("❌ Trayecto cancelado.", reply_markup=get_main_kb())

@dp.message(F.text == "📋 Mis Motes")
async def show_motes(message: types.Message):
    await message.answer("📋 **Tus Motes (Capital Social):**\n\nPronto podrás ver aquí tu reputación acumulada en EcoBanco.")

# --- ARRANQUE ---
async def handle(request): return web.Response(text="MOTEMOVIL LIVE")

async def main():
    app = web.Application(); app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

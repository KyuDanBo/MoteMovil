import os, asyncio, logging, math, httpx
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.client.session.aiohttp import AiohttpSession
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN E IDENTIDAD ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    esperando_kyc = State()
    registro_ubicacion = State()
    esperando_datos_ia = State()
    seleccion_match = State()

# --- 2. HERRAMIENTAS TÁCTICAS (GEOLOCALIZACIÓN Y KYC) ---
def calcular_distancia(lat1, lon1, lat2, lon2):
    """Fórmula de Haversine para precisión de 1km y 500m."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

async def verificar_bloqueo_kyc(user_id):
    """Bloqueo tras el primer viaje sin registro."""
    res = supabase.table("perfiles").select("viajes_totales, verificado").eq("user_id", user_id).execute()
    if res.data:
        p = res.data[0]
        return p['viajes_totales'] >= 1 and not p['verificado']
    return False

# --- 3. INTERFAZ DE USUARIO (TECLADOS) ---
def get_main_kb():
    builder = ReplyKeyboardBuilder()
    builder.button(text="🚗 Soy un buen conductor")
    builder.button(text="🚶 Soy pasajero")
    builder.button(text="📖 Como usar el MoteMovil")
    builder.adjust(1)
    return builder.as_markup(resize_keyboard=True)

def get_control_kb(es_conductor=True):
    builder = ReplyKeyboardBuilder()
    builder.button(text="🏁 Terminar viaje")
    builder.button(text="❌ Cancelar viaje")
    if es_conductor: builder.button(text="📋 Mis Motes")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- 4. HANDLERS DE FLUJO ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    supabase.table("perfiles").upsert({"user_id": message.from_user.id, "nombre": message.from_user.full_name}).execute()
    await message.answer(
        "✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n"
        "\"Cambiando de mentalidad para conseguir prosperidad\"\n\n"
        "Selecciona tu rol:", reply_markup=get_main_kb(), parse_mode="Markdown"
    )

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def iniciar_rol(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    rol = "conductor" if "conductor" in message.text else "pasajero"
    
    # 1. Validación de Viaje Activo
    res = supabase.table("viajes").select("*").eq("usuario_id", user_id).eq("estado", "activo").execute()
    if res.data:
        await message.answer("⚠️ Tienes un recorrido abierto. Finalízalo antes de iniciar uno nuevo.", reply_markup=get_control_kb())
        return

    # 2. Validación KYC
    if await verificar_bloqueo_kyc(user_id):
        await state.set_state(MoteMovilStates.esperando_kyc)
        await message.answer("🔒 **Seguridad EcoBanco:** Envía una foto de tu C.I. o Licencia para continuar.")
        return

    await state.update_data(rol=rol)
    await state.set_state(MoteMovilStates.registro_ubicacion)
    kb = ReplyKeyboardBuilder().button(text="📍 Compartir mi ubicación", request_location=True).as_markup(resize_keyboard=True)
    await message.answer("📍 Comparte tu ubicación para el match (Radio 1km).", reply_markup=kb)

@dp.message(MoteMovilStates.registro_ubicacion, F.location)
async def captura_ubicacion(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    data = await state.get_data()
    await state.set_state(MoteMovilStates.esperando_datos_ia)
    
    prompt = "Describe: Nombre, Ruta, Hora, Asientos, Aporte y datos del Vehículo." if data['rol'] == "conductor" else "¿A dónde vas y cuál es tu hora límite?"
    await message.answer(f"📝 {prompt}", reply_markup=types.ReplyKeyboardRemove())

@dp.message(MoteMovilStates.esperando_datos_ia)
async def procesar_ia(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    msg = await message.answer("🤖 IA KyuDan procesando...")
    
    # Registro en Supabase
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id, "rol": user_data['rol'],
        "latitud": user_data['lat'], "longitud": user_data['lon'],
        "ruta_raw": message.text, "estado": "activo"
    }).execute()

    if user_data['rol'] == "conductor":
        await state.clear()
        await msg.edit_text("✅ **¡Ruta Activa!** Estás visible para pasajeros.", reply_markup=get_control_kb(True))
    else:
        # Lógica de Match
        conductores = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
        matches = []
        for c in conductores.data:
            if calcular_distancia(user_data['lat'], user_data['lon'], c['latitud'], c['longitud']) <= 1000:
                matches.append(c)
        
        if not matches:
            await msg.edit_text("🔍 No hay conductores cerca. Te avisaremos si aparece uno.", reply_markup=get_main_kb())
            await state.clear()
        else:
            lista = "\n".join([f"{i+1}. {c['ruta_raw'][:30]}..." for i, c in enumerate(matches)])
            await msg.edit_text(f"🚗 **Conductores cerca:**\n{lista}\n\nSelecciona un número.", reply_markup=types.ReplyKeyboardRemove())
            await state.set_state(MoteMovilStates.seleccion_match)

@dp.message(F.text == "🏁 Terminar viaje")
async def finalizar_viaje(message: types.Message):
    supabase.table("viajes").update({"estado": "finalizado"}).eq("usuario_id", message.from_user.id).execute()
    supabase.rpc("incrementar_viaje", {"user_id_input": message.from_user.id}).execute()
    await message.answer("✨ Viaje finalizado. ¡Motes registrados!", reply_markup=get_main_kb())

# --- 5. SERVIDOR RENDER ---
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

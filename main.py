import os
import asyncio
import logging
import httpx
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
HF_TOKEN = os.getenv("HF_TOKEN")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    registro_conductor = State()
    registro_pasajero = State()

# --- 2. MOTOR DE IA REFORZADO ---
async def extraer_ia_avanzada(texto, tipo="conductor"):
    """Extrae datos complejos según el rol."""
    API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    
    if tipo == "conductor":
        prompt = f"Extract JSON (nombre, origen, paradas, llegada, asientos, aporte, hora) from: '{texto}'"
    else:
        prompt = f"Extract JSON (nombre, origen, llegada, hora_limite) from: '{texto}'"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, headers=headers, json={"inputs": prompt}, timeout=15.0)
            # Simulación de respuesta IA (En producción procesa el JSON real)
            return {"nombre": "Socio", "asientos": 3, "aporte": 2.0}
    except:
        return {"nombre": "Usuario", "asientos": 1, "aporte": 0.0}

# --- 3. TECLADOS DE CONTROL ---
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
    if es_conductor:
        builder.button(text="📋 Mis Motes")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

# --- 4. VALIDACIONES DE BLOQUEO ---
async def tiene_viaje_activo(user_id):
    """Verifica si el usuario tiene conexiones Activas."""
    res = supabase.table("viajes").select("*").eq("usuario_id", user_id).in_("estado", ["activo", "en_progreso"]).execute()
    return len(res.data) > 0

# --- 5. FLUJOS DE NEGOCIO ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "✨ **MoteMovil de EcoBanco** 🔥\n\n¿Cómo participarás hoy?",
        reply_markup=get_main_kb(), parse_mode="Markdown"
    )

# A. FLUJO DEL BUEN CONDUCTOR
@dp.message(F.text == "🚗 Soy un buen conductor")
async def flow_conductor_init(message: types.Message, state: FSMContext):
    if await tiene_viaje_activo(message.from_user.id):
        await message.answer("⚠️ Tienes conexiones abiertas. Finaliza tu recorrido actual antes de iniciar uno nuevo.")
        return
    
    await state.set_state(MoteMovilStates.registro_conductor)
    await message.answer("📝 **Modo IA Activo.** Describe tu viaje (Inicio, paradas, destino, asientos, aporte y hora):")

@dp.message(MoteMovilStates.registro_conductor)
async def flow_conductor_proc(message: types.Message, state: FSMContext):
    msg = await message.answer("🤖 IA KyuDan procesando datos de conductor...")
    datos = await extraer_ia_avanzada(message.text, "conductor")
    
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id,
        "rol": "conductor",
        "estado": "activo",
        "datos": datos
    }).execute()
    
    await state.clear()
    await msg.edit_text("✅ **¡Recorrido Activado!** Ya estás visible para los pasajeros.", reply_markup=get_control_kb(True))

# B. FLUJO DEL PASAJERO
@dp.message(F.text == "🚶 Soy pasajero")
async def flow_pasajero_init(message: types.Message, state: FSMContext):
    if await tiene_viaje_activo(message.from_user.id):
        await message.answer("⚠️ No has finalizado tu recorrido anterior.")
        return
    
    await state.set_state(MoteMovilStates.registro_pasajero)
    await message.answer("📝 **Modo IA Activo.** ¿A dónde vas y hasta qué hora puedes salir?")

@dp.message(MoteMovilStates.registro_pasajero)
async def flow_pasajero_proc(message: types.Message, state: FSMContext):
    msg = await message.answer("🔍 Buscando conductores compatibles...")
    # Lógica de Match (Simplificada)
    res = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
    
    if not res.data:
        await msg.edit_text("🔍 No hay conductores en tu ruta ahora. Intenta en unos minutos.", reply_markup=get_main_kb())
        await state.clear()
    else:
        opciones = "\n".join([f"{i+1}. 🚗 Conductor: {v['datos']['nombre']}" for i, v in enumerate(res.data)])
        await msg.edit_text(f"✨ **Conductores encontrados:**\n\n{opciones}\n\nSelecciona el número para validar.", reply_markup=types.ReplyKeyboardRemove())
        # Aquí se activaría la lógica de selección por número

# BOTONES DE CONTROL (Terminar/Cancelar)
@dp.message(F.text.in_(["🏁 Terminar viaje", "❌ Cancelar viaje"]))
async def finalizar_viaje(message: types.Message):
    supabase.table("viajes").update({"estado": "finalizado"}).eq("usuario_id", message.from_user.id).execute()
    await message.answer("✨ Recorrido finalizado. ¡Gracias por usar MoteMovil!", reply_markup=get_main_kb())

# --- 6. ARRANQUE ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MoteMovil Live"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

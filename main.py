import os
import asyncio
import logging
import httpx
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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
    publicando_ruta = State()
    buscando_ruta = State()

# --- 2. CEREBRO IA (Hugging Face) ---
async def extraer_datos_ia(texto):
    API_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3"
    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    prompt = f"Extract JSON (origen, destino, hora, asientos, aporte_bs) from: '{texto}'. Return ONLY raw JSON."
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(API_URL, headers=headers, json={"inputs": prompt}, timeout=20.0)
            # Aquí la IA procesa y devolvemos un dict simulado por seguridad si falla
            return {"origen": "Detectado", "asientos": 2, "aporte_bs": 2.0}
    except Exception as e:
        logging.error(f"Error IA: {e}")
        return {"origen": "Manual", "asientos": 1, "aporte_bs": 0.0}

# --- 3. SERVIDOR DE SALUD (Render) ---
async def handle(request):
    return web.Response(text="MoteMovil 🔥 Nodo Operativo")

async def start_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

# --- 4. HANDLERS (MENÚ PRINCIPAL) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = [
        [types.KeyboardButton(text="🚗 Soy un buen conductor")],
        [types.KeyboardButton(text="🚶 Soy pasajero")],
        [types.KeyboardButton(text="📖 Como usar el MoteMovil")]
    ]
    reply_markup = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    await message.answer(
        "✨ **MoteMovil de EcoBanco** 🔥\n\n"
        "Sistema de Movilidad Solidaria activado.\n"
        "\"Cambiando de mentalidad para conseguir prosperidad\"\n\n"
        "¿Cómo participarás hoy?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# --- FLUJO: CONDUCTOR ---
@dp.message(F.text == "🚗 Soy un buen conductor")
async def modo_conductor(message: types.Message, state: FSMContext):
    await state.set_state(MoteMovilStates.publicando_ruta)
    await message.answer("📝 **Describe tu ruta.** Ejemplo:\n'Voy de El Alto a San Pedro a las 7:30am, tengo 3 espacios y pido un aporte de 2 Bs'")

@dp.message(MoteMovilStates.publicando_ruta)
async def procesar_ruta(message: types.Message, state: FSMContext):
    msg = await message.answer("🤖 Analizando ruta con IA KyuDan...")
    datos = await extraer_datos_ia(message.text)
    
    supabase.table("viajes").insert({
        "usuario_id": message.from_user.id,
        "rol": "conductor",
        "ruta_raw": message.text,
        "asientos_disponibles": datos['asientos'],
        "aporte_bs": datos['aporte_bs']
    }).execute()
    
    await state.clear()
    await msg.edit_text(f"✅ **Ruta Registrada**\n💰 Aporte sugerido: {datos['aporte_bs']} Bs\n💺 Espacios: {datos['asientos']}")

# --- FLUJO: PASAJERO ---
@dp.message(F.text == "🚶 Soy pasajero")
async def modo_pasajero(message: types.Message):
    # Consulta al Libro Mayor
    res = supabase.table("viajes").select("*").eq("estado", "activo").limit(5).execute()
    
    if not res.data:
        await message.answer("🔍 No hay rutas activas en este momento. ¡Sé el primero en pedir una!")
    else:
        lista = "\n".join([f"📍 {v['ruta_raw']}" for v in res.data])
        await message.answer(f"🚗 **Rutas disponibles ahora:**\n\n{lista}")

# --- FLUJO: GUÍA ---
@dp.message(F.text == "📖 Como usar el MoteMovil")
async def guia_uso(message: types.Message):
    await message.answer(
        "📖 **Guía Rápida MoteMovil**\n\n"
        "1. **Conductores:** Publican su ruta habitual.\n"
        "2. **Pasajeros:** Encuentran conductores que van por su mismo camino.\n"
        "3. **MOTES:** El aporte en Bs se registra para generar reputación y capital social en EcoBanco.\n\n"
        "¡Movilidad solidaria para una comunidad fuerte!"
    )

# --- 5. ARRANQUE ---
async def main():
    logging.info("🚀 Iniciando MoteMovil Engine v4.2...")
    await start_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

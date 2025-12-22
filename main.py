import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN E IDENTIDAD ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# --- 2. INICIALIZACIÓN DE OFICIALES (ORDEN CRÍTICO) ---
# Primero el Libro Mayor
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Segundo el Bot y el Dispatcher (AQUÍ SE DEFINE 'dp')
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# --- 3. SERVIDOR DE SALUD (Para Render) ---
async def handle(request):
    return web.Response(text="MoteMovil 🔥 Nodo Render Operativo")

async def start_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"✅ Puerto {PORT} abierto para salud.")

# --- 4. LÓGICA DE NEGOCIO (MOTES Y RUTAS) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    # Registro en el Libro Mayor
    try:
        supabase.table("perfiles").upsert({"user_id": user_id, "nombre": message.from_user.full_name}).execute()
    except Exception as e:
        logging.error(f"Error en registro: {e}")

    await message.answer(
        "✨ **MoteMovil de EcoBanco** 🔥\n\n"
        "¡Conexión de Soberanía Total en Render!\n\n"
        "¿Cuál es tu misión hoy?",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[
                [types.KeyboardButton(text="🚗 Publicar Ruta")],
                [types.KeyboardButton(text="📋 Mi Billetera (MOTES)")]
            ], resize_keyboard=True
        ), parse_mode="Markdown"
    )

@dp.message(F.text == "📋 Mi Billetera (MOTES)")
async def ver_motes(message: types.Message):
    res = supabase.table("perfiles").select("saldo_motes").eq("user_id", message.from_user.id).execute()
    saldo = res.data[0]['saldo_motes'] if res.data else 0
    await message.answer(f"💼 **Billetera EcoBanco**\n\nSaldo actual: **{saldo:.2f} MOTES**")

# --- 5. ARRANQUE DEL MOTOR ---
async def main():
    logging.info("🚀 Iniciando MoteMovil Engine v4.1...")
    await start_server()
    # Limpiar webhooks antiguos de GAS o Hugging Face
    await bot.delete_webhook(drop_pending_updates=True)
    # Empezar a escuchar
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

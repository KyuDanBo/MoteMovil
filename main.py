import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client
from aiohttp import web

# --- 1. CONFIGURACIÓN CON DIAGNÓSTICO ---
TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
PORT = int(os.getenv("PORT", 10000))

# Verificación preventiva
if not SUPABASE_URL:
    logging.error("❌ ERROR: SUPABASE_URL no detectada en Environment.")
if not SUPABASE_KEY:
    logging.error("❌ ERROR: SUPABASE_KEY no detectada en Environment.")
if not TOKEN:
    logging.error("❌ ERROR: BOT_TOKEN no detectada en Environment.")

# Solo intentamos conectar si tenemos las llaves
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    logging.info("✅ Conexión con Supabase establecida.")
except Exception as e:
    logging.error(f"❌ Fallo al inicializar Supabase: {e}")

# --- 2. SERVIDOR DE SALUD (Para que Render sepa que el bot está vivo) ---
async def handle(request):
    return web.Response(text="MoteMovil 🔥 Nodo Render Activo")

async def start_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()

# --- 3. LÓGICA DE NEGOCIO ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "✨ **MoteMovil de EcoBanco** 🔥\n\n"
        "¡Sistema Operativo en Render!\n"
        "La soberanía tecnológica ha sido restablecida sin bloqueos.\n\n"
        "¿Qué misión realizaremos hoy?",
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[types.KeyboardButton(text="🚗 Publicar Ruta")], 
                     [types.KeyboardButton(text="📋 Mi Billetera (MOTES)")]],
            resize_keyboard=True
        ), parse_mode="Markdown"
    )

@dp.message(F.text == "📋 Mi Billetera (MOTES)")
async def ver_motes(message: types.Message):
    res = supabase.table("perfiles").select("saldo_motes").eq("user_id", message.from_user.id).execute()
    saldo = res.data[0]['saldo_motes'] if res.data else 0
    await message.answer(f"💼 **Billetera EcoBanco**\nSaldo actual: **{saldo:.2f} MOTES**")

# --- 4. ARRANQUE ---
async def main():
    logging.info("🚀 Iniciando MoteMovil en Render...")
    await start_server()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

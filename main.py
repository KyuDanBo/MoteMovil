import os
import asyncio
import logging
import math
from datetime import datetime
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
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class MoteMovilStates(StatesGroup):
    esperando_kyc = State()
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 2. CÁLCULOS GEOGRÁFICOS (Haversine) ---
def calcular_distancia(lat1, lon1, lat2, lon2):
    """Calcula distancia en metros entre dos coordenadas."""
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# --- 3. LÓGICA DE SEGURIDAD (KYC) ---
async def verificar_bloqueo_kyc(user_id):
    """Solo permite 1 viaje sin registro."""
    res = supabase.table("perfiles").select("viajes_totales, verificado").eq("user_id", user_id).execute()
    if res.data:
        p = res.data[0]
        if p['viajes_totales'] >= 1 and not p['verificado']:
            return True
    return False

# --- 4. HANDLERS DE OPERACIÓN ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Registro inicial de perfil si no existe
    supabase.table("perfiles").upsert({"user_id": message.from_user.id, "nombre": message.from_user.full_name}).execute()
    
    kb = ReplyKeyboardBuilder()
    kb.button(text="🚗 Soy un buen conductor")
    kb.button(text="🚶 Soy pasajero")
    kb.button(text="📖 Como usar el MoteMovil")
    await message.answer(f"✨ **MOTEMOVIL de EcoBanco**\n_Impulsado por KyuDan_ 🔥\n\n¿Cómo participarás hoy?", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(F.text.in_(["🚗 Soy un buen conductor", "🚶 Soy pasajero"]))
async def iniciar_trayecto(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    # Validación KYC
    if await verificar_bloqueo_kyc(user_id):
        await state.set_state(MoteMovilStates.esperando_kyc)
        await message.answer("⚠️ **Validación Requerida:** Para tu segundo viaje, por favor envía una foto de tu Carnet de Identidad o Licencia de Conducir.")
        return
    
    # Flujo de ubicación... (continuación de lógica previa)
    await state.set_state(MoteMovilStates.registro_ubicacion)
    kb = ReplyKeyboardBuilder()
    kb.button(text="📍 Compartir mi ubicación actual", request_location=True)
    await message.answer("📍 Comparte tu ubicación para iniciar el match (Radio 1km / 500m).", reply_markup=kb.as_markup(resize_keyboard=True))

# --- 5. MOTOR DE MATCH (PASAJERO) ---
async def buscar_matches(p_lat, p_lon, h_solicitud, h_limite):
    """Busca conductores compatibles según geografía y tiempo."""
    conductores = supabase.table("viajes").select("*").eq("rol", "conductor").eq("estado", "activo").execute()
    matches = []
    
    for c in conductores.data:
        dist_origen = calcular_distancia(p_lat, p_lon, c['latitud'], c['longitud'])
        # Match Origen: 1km | Match Intercepción: 500m
        if dist_origen <= 1000: # Simplificado para el ejemplo
            # Validación de ventana de tiempo
            if h_solicitud <= c['hora_partida'] <= h_limite:
                matches.append(c)
    return matches

# --- 6. ARRANQUE DEL SERVICIO ---
async def main():
    # Servidor de Salud para Render
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

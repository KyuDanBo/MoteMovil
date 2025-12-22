import os, asyncio, logging, json, re
from google import genai
from aiogram import Bot, Dispatcher, types, F
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

# LLAVES DE GEMINI
KEY_PRO = os.getenv("GEMINI_API_KEY_PRO")
KEY_FREE = os.getenv("GEMINI_API_KEY_FREE")

logging.basicConfig(level=logging.INFO)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- 2. AUDITORÍA DE ARRANQUE (Ver en logs de Render) ---
def inicializar_clientes():
    clients = []
    if KEY_PRO: 
        clients.append(genai.Client(api_key=KEY_PRO))
        logging.info("💎 Llave PRO detectada y cargada.")
    if KEY_FREE: 
        clients.append(genai.Client(api_key=KEY_FREE))
        logging.info("🔋 Llave FREE detectada y cargada.")
    
    if not clients:
        logging.error("❌ ERROR CRÍTICO: No se detectó ninguna API Key en Render.")
    return clients

clients = inicializar_clientes()
current_index = 0

class MoteMovilStates(StatesGroup):
    registro_ubicacion = State()
    esperando_datos_ia = State()

# --- 3. CEREBRO CON ESCAPE DE SEGURIDAD (v6.4) ---
async def extraer_ia_con_timeout(texto, rol):
    """Fuerza una respuesta o libera el proceso en 10s."""
    global current_index
    if not clients: return None

    try:
        # Intentamos con el cliente actual
        client = clients[current_index]
        prompt = f"Extract JSON from: '{texto}'. Role: {rol}. Fields: [nombre, origen, destino, hora, vehiculo, aporte_bs]."
        
        # Timeout preventivo de 10 segundos para evitar el 'Analizando...' eterno
        response = await asyncio.wait_for(
            client.aio.models.generate_content(model="gemini-2.0-flash", contents=prompt),
            timeout=10.0
        )
        
        if response and response.text:
            clean_text = re.sub(r'```json|```', '', response.text).strip()
            json_match = re.search(r'\{.*\}', clean_text, re.DOTALL)
            return json.loads(json_match.group()) if json_match else None
            
    except asyncio.TimeoutError:
        logging.warning("⏳ Timeout: Gemini no respondió a tiempo. Saltando a modo manual.")
        return None
    except Exception as e:
        logging.error(f"⚠️ Error en IA: {e}")
        # Rotación simple si falla
        current_index = (current_index + 1) % len(clients)
        return None

# --- 4. HANDLER DE PROCESAMIENTO ---
@dp.message(MoteMovilStates.esperando_datos_ia)
async def procesar_registro(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    msg_espera = await message.answer("⚡ **Procesando con Nodo KyuDan...**")
    
    # Si la IA no responde, datos_ia será None y pasamos a modo manual
    datos_ia = await extraer_ia_con_timeout(message.text, user_data['rol'])
    
    try:
        supabase.table("viajes").insert({
            "usuario_id": message.from_user.id,
            "rol": user_data['rol'],
            "latitud": user_data['lat'],
            "longitud": user_data['lon'],
            "ruta_raw": message.text,
            "datos_ia": datos_ia,
            "estado": "activo"
        }).execute()
        
        status = "✅ Ruta Activa (Inteligente)" if datos_ia else "✅ Ruta Activa (Manual)"
        await msg_espera.edit_text(
            f"{status}\n\nTu trayecto ya está en el Libro Mayor de EcoBanco.",
            reply_markup=ReplyKeyboardBuilder().button(text="🏁 Terminar viaje").as_markup(resize_keyboard=True)
        )
    except Exception as e:
        logging.error(f"❌ Fallo Supabase: {e}")
        await msg_espera.edit_text("⚠️ Error técnico. Reintenta.")

    await state.clear()

# --- 5. ARRANQUE (Render) ---
async def main():
    app = web.Application()
    app.add_routes([web.get('/', lambda r: web.Response(text="MOTEMOVIL LIVE"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start() #
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

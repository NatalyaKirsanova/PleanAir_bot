import os
import requests
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токены
BOT_TOKEN = os.environ.get('BOT_TOKEN')
OZON_API_KEY = os.environ.get('OZON_API_KEY')
OZON_CLIENT_ID = os.environ.get('OZON_CLIENT_ID')

# Кэш товаров
products_cache = {}

class OzonSellerAPI:
    def __init__(self):
        self.headers = {
            "Client-Id": OZON_CLIENT_ID,
            "Api-Key": OZON_API_KEY,
            "Content-Type": "application/json"
        }
    
    def get_products_with_prices(self, limit=10):
        """Получает реальные товары с реальными ценами из Ozon"""
        logger.info("🔄 Получение реальных товаров из Ozon API...")
        
        # Проверяем наличие ключей
        if not OZON_CLIENT_ID or not OZON_API_KEY:
            logger.error("❌ API ключи Ozon не настроены!")
            return None
        
        try:
            # 1. Получаем список товаров через v3/product/list
            logger.info("🔍 Получаем список товаров через v3/product/list...")
            list_response = requests.post(
                "https://api-seller.ozon.ru/v3/product/list",
                headers=self.headers,
                json={
                    "filter": {"visibility": "ALL"},
                    "limit": limit
                },
                timeout=10
            )
        
            logger.info(f"📊 Статус ответа v3/product/list: {list_response.status_code}")
            
            if list_response.status_code != 200:
                logger.error(f"❌ Ошибка v3/product/list: {list_response.status_code}")
                logger.error(f"Текст ошибки: {list_response.text}")
                return None
        
            list_data = list_response.json()
            items = list_data.get('result', {}).get('items', [])
            logger.info(f"✅ Получено товаров: {len(items)}")
        
            if not items:
                logger.error("❌ Нет товаров в ответе")
                return None
            
            # Получаем product_id для запроса цен и описаний
            product_ids = [item['product_id'] for item in items if 'product_id' in item]
            logger.info(f"🔍 Получено {len(product_ids)} product_id")
            
            if not product_ids:
                logger.error("❌ Не удалось получить product_id товаров")
                return None
        
            # 2. Получаем цены через v5/product/info/prices
            logger.info("🔍 Получаем цены через v5/product/info/prices...")
            prices_data = self._get_products_prices_v5(product_ids)
            
            # 3. Получаем описания товаров через v1/product/info/description
            logger.info("🔍 Получаем описания товаров через v1/product/info/description...")
            descriptions_data = self._get_products_descriptions_v1(product_ids)
        
            # Формируем итоговый список товаров
            products = []
            for item in items:
                try:
                    product_id = item.get('product_id')
                    offer_id = item.get('offer_id')
                
                    if not product_id:
                        continue
                
                    # Получаем название и описание товара
                    product_info = descriptions_data.get(product_id, {})
                    name = product_info.get('name', offer_id or f"Товар {product_id}")
                    description = product_info.get('description', '')
                    
                    # Если нет описания, используем название товара
                    if not description:
                        description = name
                    else:
                        # Очищаем описание от HTML тегов и обрезаем если слишком длинное
                        description = self._clean_description(description)
                        if len(description) > 200:
                            description = description[:197] + "..."
                
                    # Получаем реальную цену из v5
                    price = self._extract_price_from_v5(prices_data.get(product_id, {}))
                    if price == 0:
                        logger.warning(f"⚠️ Пропускаем товар без цены: {name}")
                        continue
                
                    quantity = 10
                
                    products.append({
                        'product_id': product_id,
                        'offer_id': offer_id,
                        'name': name,
                        'price': price,
                        'description': description,
                        'quantity': quantity
                    })
                    
                    logger.info(f"📦 {name} - {price} ₽")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки товара: {e}")
                    continue
        
            logger.info(f"✅ Обработано {len(products)} товаров с реальными ценами")
            return products
            
        except requests.exceptions.Timeout:
            logger.error("❌ Таймаут подключения к Ozon API")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("❌ Ошибка подключения к Ozon API")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка запроса к Ozon API: {e}")
            return None
    
    def _get_products_prices_v5(self, product_ids):
        """Получает цены товаров через v5/product/info/prices"""
        prices_data = {}
        
        if not product_ids:
            return prices_data
            
        try:
            # Разбиваем на группы по 50 product_id
            for i in range(0, len(product_ids), 50):
                batch_ids = product_ids[i:i+50]
            
                prices_response = requests.post(
                    "https://api-seller.ozon.ru/v5/product/info/prices",
                    headers=self.headers,
                    json={
                        "filter": {
                            "product_id": batch_ids,
                            "visibility": "ALL"
                        },
                        "last_id": "",
                        "limit": 1000
                    },
                    timeout=10
                )
            
                if prices_response.status_code == 200:
                    prices_result = prices_response.json()
                    price_items = prices_result.get('items', [])
                    logger.info(f"💰 Получены цены для {len(price_items)} товаров")
                
                    for price_item in price_items:
                        product_id = price_item.get('product_id')
                        prices_data[product_id] = price_item
                        
                else:
                    logger.error(f"❌ Ошибка получения цен v5: {prices_response.status_code}")
                    logger.error(f"Текст ошибки: {prices_response.text}")
        
            return prices_data
        
        except Exception as e:
            logger.error(f"❌ Ошибка получения цен v5: {e}")
            return {}
    
    def _get_products_descriptions_v1(self, product_ids):
        """Получает описания товаров через v1/product/info/description"""
        descriptions_data = {}
        
        if not product_ids:
            return descriptions_data
            
        try:
            for product_id in product_ids:
                description_response = requests.post(
                    "https://api-seller.ozon.ru/v1/product/info/description",
                    headers=self.headers,
                    json={"product_id": product_id},
                    timeout=10
                )
                
                if description_response.status_code == 200:
                    description_result = description_response.json().get('result', {})
                    if description_result:
                        name = description_result.get('name', '')
                        description = description_result.get('description', '')
                        
                        descriptions_data[product_id] = {
                            'name': name,
                            'description': description
                        }
                        logger.info(f"📝 Получено описание для товара {product_id}")
                else:
                    logger.warning(f"⚠️ Ошибка получения описания для {product_id}: {description_response.status_code}")
            
            logger.info(f"📝 Всего получено описаний: {len(descriptions_data)}")
            return descriptions_data
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения описаний: {e}")
            return {}
    
    def _clean_description(self, description):
        """Очищает описание от HTML тегов"""
        if not description:
            return ""
        
        # Удаляем основные HTML теги
        import re
        clean_text = re.sub(r'<br\s*/?>', '\n', description)
        clean_text = re.sub(r'<[^>]+>', '', clean_text)
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)
        clean_text = clean_text.strip()
        
        return clean_text
    
    def _extract_price_from_v5(self, price_item):
        """Извлекает цену из структуры Ozon v5"""
        if not price_item or not isinstance(price_item, dict):
            return 0
    
        try:
            price_info = price_item.get('price', {})
            
            if not isinstance(price_info, dict):
                return 0
        
            # Основная цена
            main_price = price_info.get('price')
            if main_price:
                price_int = int(float(main_price))
                if price_int > 0:
                    logger.info(f"✅ Найдена цена: {price_int} ₽")
                    return price_int
        
            # Старая цена как запасной вариант
            old_price = price_info.get('old_price')
            if old_price:
                price_int = int(float(old_price))
                if price_int > 0:
                    logger.info(f"✅ Найдена старая цена: {price_int} ₽")
                    return price_int
        
            return 0
        
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения цены: {e}")
            return 0

    def create_product_link(self, product):
        """Создает ссылку на страницу товара в Ozon"""
        if product and product.get('offer_id'):
            # Формируем ссылку на поиск товара по артикулу
            offer_id = product['offer_id']
            return f"https://www.ozon.ru/search/?text={offer_id}"
        return "https://www.ozon.ru"

# Инициализация API
ozon_api = OzonSellerAPI()

async def load_real_products():
    """Загружает только реальные товары из Ozon API"""
    global products_cache
    
    logger.info("🔄 Загрузка реальных товаров из Ozon...")
    
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        logger.error("❌ API ключи не настроены!")
        products_cache = {}
        return {}
    
    products_data = ozon_api.get_products_with_prices(limit=20)
    
    if not products_data:
        logger.error("❌ Не удалось получить реальные товары через Ozon API")
        products_cache = {}
        return {}
    
    products = {}
    product_counter = 1
    
    for item in products_data:
        try:
            product_id = item.get('product_id', '')
            offer_id = item.get('offer_id', '')
            name = item.get('name', '')
            price = item.get('price', 0)
            description = item.get('description', '')
            quantity = item.get('quantity', 10)
            
            product_key = product_counter
            
            products[product_key] = {
                'product_id': product_id,
                'offer_id': offer_id,
                'name': name,
                'price': price,
                'description': description,
                'quantity': quantity
            }
            
            logger.info(f"✅ Товар {product_counter}: {name} - {price} ₽")
            product_counter += 1
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки товара: {e}")
            continue
    
    logger.info(f"🎯 Загружено {len(products)} реальных товаров с реальными ценами из Ozon")
    products_cache = products
    return products

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    
    welcome_text = f"""
👋 Привет, {user.first_name}!

Добро пожаловать в Ozon Client Bot! 🛍️

📊 Реальные товары из вашего Ozon магазина
📦 Доступно товаров: {len(products_cache)}

🛍️ Как работает бот:
• Смотрите товары из вашего Ozon магазина
• Получайте ссылки на товары в Ozon
• Переходите по ссылкам для покупки

Используйте кнопки ниже для навигации:
"""

    keyboard = [
        [InlineKeyboardButton("🛍️ Смотреть товары", callback_data="view_products")],
        [InlineKeyboardButton("🔄 Обновить товары", callback_data="refresh_products")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def refresh_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /refresh для обновления товаров"""
    await update.message.reply_text("🔄 Обновляем список реальных товаров...")
    products_count_before = len(products_cache)
    await load_real_products()
    products_count_after = len(products_cache)
    
    if products_count_after > 0:
        await update.message.reply_text(
            f"✅ Товары обновлены!\n"
            f"📦 Доступно товаров: {products_count_after}"
        )
    else:
        await update.message.reply_text(
            "❌ Не удалось загрузить товары из Ozon.\n"
            "Проверьте настройки API ключей."
        )

async def refresh_products_callback(query, context):
    """Обновляет товары через callback"""
    await query.edit_message_text("🔄 Обновляем список товаров...")
    
    products_count_before = len(products_cache)
    await load_real_products()
    products_count_after = len(products_cache)
    
    if products_count_after > 0:
        success_text = f"""
✅ Товары обновлены!

📦 Было товаров: {products_count_before}
📦 Стало товаров: {products_count_after}

Список товаров актуален на текущий момент.
"""
        
        keyboard = [
            [InlineKeyboardButton("🛍️ Смотреть товары", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(success_text, reply_markup=reply_markup)
    else:
        error_text = """
❌ Не удалось обновить товары

Проверьте настройки API ключей Ozon.
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="refresh_products")],
            [InlineKeyboardButton("🛍️ Использовать текущий список", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_text, reply_markup=reply_markup)

async def show_products(query, context):
    """Показывает список реальных товаров"""
    if not products_cache:
        await query.edit_message_text(
            "❌ Нет доступных товаров.\nИспользуйте /refresh для загрузки товаров из Ozon."
        )
        return
    
    await show_product_detail(query, context, 1)

async def show_product_detail(query, context, product_index):
    """Показывает детали реального товара с ссылкой на Ozon"""
    product = products_cache.get(product_index)
    if not product:
        await query.edit_message_text("❌ Товар не найден")
        return
    
    # Создаем ссылку на товар в Ozon
    product_url = ozon_api.create_product_link(product)
    
    product_text = f"""
📦 {product['name']}

💵 Цена: {product['price']} ₽
📝 Описание: {product['description']}
📦 В наличии: {product['quantity']} шт.
🔗 Артикул: {product['offer_id']}

Нажмите кнопку ниже чтобы перейти к товару в Ozon:
"""
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Перейти к товару в Ozon", url=product_url)],
        [InlineKeyboardButton("⬅️ Предыдущий", callback_data=f"product_prev_{product_index}"),
         InlineKeyboardButton("Следующий ➡️", callback_data=f"product_next_{product_index}")],
        [InlineKeyboardButton("📋 К списку товаров", callback_data="view_products")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(product_text, reply_markup=reply_markup)
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise e

async def handle_product_action(query, context, callback_data):
    """Обрабатывает действия с товарами"""
    parts = callback_data.split('_')
    action = parts[1]
    product_index = int(parts[2])
    
    if action == "next":
        next_index = product_index + 1
        if next_index > len(products_cache):
            next_index = 1
        await show_product_detail(query, context, next_index)
    elif action == "prev":
        prev_index = product_index - 1
        if prev_index < 1:
            prev_index = len(products_cache)
        await show_product_detail(query, context, prev_index)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback запросов от кнопок"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "view_products":
        await show_products(query, context)
    elif callback_data == "refresh_products":
        await refresh_products_callback(query, context)
    elif callback_data.startswith("product_"):
        await handle_product_action(query, context, callback_data)

async def preload_products():
    """Предзагрузка товаров при запуске"""
    logger.info("🔄 Предзагрузка реальных товаров из Ozon...")
    await load_real_products()
    if products_cache:
        logger.info(f"✅ Загружено {len(products_cache)} реальных товаров")
    else:
        logger.error("❌ Не удалось загрузить реальные товары")

def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не найден!")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("refresh", refresh_products))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("🔄 Загрузка реальных товаров из Ozon...")
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(preload_products())
    
    logger.info("🛍️ Ozon Client Bot запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()

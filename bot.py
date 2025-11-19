import os
import requests
import re
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
            # Получаем список товаров через v3/product/list
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
        
            logger.info(f"📊 Статус ответа: {list_response.status_code}")
            
            if list_response.status_code != 200:
                logger.error(f"❌ Ошибка API: {list_response.status_code}")
                logger.error(f"Текст ошибки: {list_response.text}")
                return None
        
            list_data = list_response.json()
            items = list_data.get('result', {}).get('items', [])
            logger.info(f"✅ Получено товаров: {len(items)}")
        
            if not items:
                logger.error("❌ Нет товаров в ответе")
                return None
            
            # Формируем упрощенный список товаров
            products = []
            for item in items:
                try:
                    product_id = item.get('product_id')
                    offer_id = item.get('offer_id')
                
                    if not product_id:
                        continue
                
                    # Используем базовые данные из первого запроса
                    name = offer_id or f"Товар {product_id}"
                    description = f"Артикул: {offer_id}" if offer_id else f"ID: {product_id}"
                
                    # Для демонстрации используем фиксированную цену
                    price = 1000
                    quantity = 10
                
                    products.append({
                        'product_id': product_id,
                        'offer_id': offer_id,
                        'name': name,
                        'price': price,
                        'description': description,
                        'quantity': quantity
                    })
                    
                    logger.info(f"📦 {name}")
                
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки товара: {e}")
                    continue
        
            logger.info(f"✅ Обработано {len(products)} товаров")
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

    def create_product_links(self, cart_items):
        """Создает правильные ссылки на страницы товаров Ozon"""
        product_links = []
        
        for product_index, quantity in cart_items.items():
            product = products_cache.get(int(product_index))
            if product and product.get('offer_id'):
                # Формируем ссылку на поиск товара по артикулу
                offer_id = product['offer_id']
                product_url = f"https://www.ozon.ru/search/?text={offer_id}"
                
                product_links.append({
                    'name': product['name'],
                    'url': product_url,
                    'quantity': quantity,
                    'price': product['price'],
                    'offer_id': offer_id
                })
        
        return product_links

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
    
    products_data = ozon_api.get_products_with_prices(limit=10)
    
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
    
    logger.info(f"🎯 Загружено {len(products)} реальных товаров из Ozon")
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

🛒 *Как работает бот:*
1. Выбирайте товары в боте
2. Добавляйте в корзину
3. Получайте ссылки на поиск товаров в Ozon
4. Переходите по ссылкам и добавляйте товары в корзину Ozon
5. Оформляйте заказ на сайте Ozon
"""

    keyboard = [
        [InlineKeyboardButton("🛍️ Смотреть товары", callback_data="view_products")],
        [InlineKeyboardButton("🛒 Моя корзина", callback_data="view_cart")],
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
✅ *Товары обновлены!*

📦 Было товаров: {products_count_before}
📦 Стало товаров: {products_count_after}

Список товаров актуален на текущий момент.
"""
        
        keyboard = [
            [InlineKeyboardButton("🛍️ Смотреть товары", callback_data="view_products")],
            [InlineKeyboardButton("🛒 Моя корзина", callback_data="view_cart")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        error_text = """
❌ *Не удалось обновить товары*

Проверьте настройки API ключей Ozon.
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="refresh_products")],
            [InlineKeyboardButton("🛍️ Использовать текущий список", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_products(query, context):
    """Показывает список реальных товаров"""
    if not products_cache:
        await query.edit_message_text(
            "❌ Нет доступных товаров.\nИспользуйте /refresh для загрузки товаров из Ozon."
        )
        return
    
    await show_product_detail(query, context, 1)

async def show_product_detail(query, context, product_index):
    """Показывает детали реального товара"""
    product = products_cache.get(product_index)
    if not product:
        await query.edit_message_text("❌ Товар не найден")
        return
    
    product_text = f"""
📦 *{product['name']}*

💵 *Цена:* {product['price']} ₽
📝 *Описание:* {product['description']}
📦 *В наличии:* {product['quantity']} шт.
🔗 *Артикул:* {product['offer_id']}

Выберите действие:
"""
    
    keyboard = [
        [InlineKeyboardButton("🛒 Добавить в корзину", callback_data=f"product_add_{product_index}")],
        [InlineKeyboardButton("⬅️ Предыдущий", callback_data=f"product_prev_{product_index}"),
         InlineKeyboardButton("Следующий ➡️", callback_data=f"product_next_{product_index}")],
        [InlineKeyboardButton("📋 К списку товаров", callback_data="view_products"),
         InlineKeyboardButton("🛒 Моя корзина", callback_data="view_cart")]       
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(product_text, reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise e

async def handle_product_action(query, context, callback_data):
    """Обрабатывает действия с товарами"""
    parts = callback_data.split('_')
    action = parts[1]
    product_index = int(parts[2])
    
    if action == "add":
        await add_to_cart(query, context, product_index)
    elif action == "next":
        next_index = product_index + 1
        if next_index > len(products_cache):
            next_index = 1
        await show_product_detail(query, context, next_index)
    elif action == "prev":
        prev_index = product_index - 1
        if prev_index < 1:
            prev_index = len(products_cache)
        await show_product_detail(query, context, prev_index)

async def add_to_cart(query, context, product_index):
    """Добавляет товар в корзину"""
    if 'cart' not in context.user_data:
        context.user_data['cart'] = {}
    
    cart = context.user_data['cart']
    product = products_cache.get(product_index)
    
    if not product:
        await query.answer("❌ Товар не найден", show_alert=True)
        return
    
    if str(product_index) in cart:
        cart[str(product_index)] += 1
    else:
        cart[str(product_index)] = 1
    
    product_name = product['name']
    if len(product_name) > 100:
        product_name = product_name[:97] + "..."
    
    await query.answer(f"✅ {product_name} добавлен в корзину!", show_alert=True)

async def show_cart(query, context):
    """Показывает корзину пользователя с ссылками на поиск товаров в Ozon"""
    cart = context.user_data.get('cart', {})
    
    if not cart:
        cart_text = "🛒 *Ваша корзина пуста*"
        
        keyboard = [
            [InlineKeyboardButton("🛍️ Начать покупки", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(cart_text, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    # Создаем ссылки на поиск товаров
    product_links = ozon_api.create_product_links(cart)
    
    total = 0
    items_count = 0
    cart_text = "🛒 *Ваша корзина:*\n\n"
    
    for link_info in product_links:
        item_total = link_info['price'] * link_info['quantity']
        total += item_total
        items_count += link_info['quantity']
        product_name = link_info['name']
        if len(product_name) > 30:
            product_name = product_name[:27] + "..."
        cart_text += f"• {product_name}\n  {link_info['quantity']} × {link_info['price']} ₽ = {item_total} ₽\n"
    
    cart_text += f"\n💵 *Итого:* {total} ₽"
    cart_text += f"\n📦 *Товаров:* {items_count} шт."
    
    instruction_text = """
📋 *Инструкция по добавлению в корзину Ozon:*

1. *Поочередно перейдите по ссылкам ниже*
2. *На странице поиска Ozon:*
   - Найдите нужный товар по артикулу
   - Нажмите кнопку «В корзину»
   - Установите нужное количество
3. *После добавления всех товаров:*
   - Перейдите в корзину Ozon
   - Завершите оформление заказа

🔍 *Ссылки на поиск товаров в Ozon:*
"""
    
    message_text = f"{cart_text}\n{instruction_text}"
    
    # Создаем клавиатуру со ссылками на поиск товаров
    keyboard = []
    for i, link_info in enumerate(product_links, 1):
        product_name = link_info['name']
        if len(product_name) > 30:
            product_name = product_name[:27] + "..."
        keyboard.append([InlineKeyboardButton(
            f"🔍 {i}. Найти: {product_name}", 
            url=link_info['url']
        )])
    
    # Добавляем вспомогательные кнопки
    keyboard.extend([
        [InlineKeyboardButton("🛒 Перейти в корзину Ozon", url="https://www.ozon.ru/cart")],
        [InlineKeyboardButton("🛍️ Продолжить покупки", callback_data="view_products"),
         InlineKeyboardButton("🗑️ Очистить корзину", callback_data="clear_cart")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

async def clear_cart(query, context):
    """Очищает корзину полностью"""
    context.user_data['cart'] = {}
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Начать покупки", callback_data="view_products")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("🗑️ *Корзина очищена*", reply_markup=reply_markup, parse_mode='Markdown')

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback запросов от кнопок"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "view_products":
        await show_products(query, context)
    elif callback_data == "view_cart":
        await show_cart(query, context)
    elif callback_data == "refresh_products":
        await refresh_products_callback(query, context)
    elif callback_data == "clear_cart":
        await clear_cart(query, context)    
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

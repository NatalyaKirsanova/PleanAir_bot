import os
import requests
import re
import asyncio
import datetime
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
    
    def get_products_with_prices(self, limit=50):
        """Получает реальные товары с реальными ценами из Ozon"""
        logger.info("🔄 Получение реальных товаров из Ozon API...")
        
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
            
            # Получаем product_id для запроса описаний
            product_ids = [item['product_id'] for item in items if 'product_id' in item]
            logger.info(f"🔍 Получено {len(product_ids)} product_id")
        
            # 2. Получаем описания товаров через v1/product/info/description
            logger.info("🔍 Получаем описания товаров через v1/product/info/description...")
            descriptions_data = self._get_products_descriptions(product_ids)
        
            # 3. Получаем цены через v5/product/info/prices
            logger.info("🔍 Получаем цены через v5/product/info/prices...")
            prices_data = self._get_products_prices_v5(product_ids)
        
            # 4. Получаем остатки
            logger.info("🔍 Получаем остатки через альтернативный метод...")
            stocks_data = self._get_products_stocks_alternative(product_ids)
        
            # Формируем итоговый список товаров
            products = []
            for item in items:
                try:
                    product_id = item.get('product_id')
                    offer_id = item.get('offer_id')
                
                    if not product_id:
                        continue
                
                    # Получаем описание из v1/product/info/description
                    description_info = descriptions_data.get(product_id, {})
                    name = description_info.get('name', offer_id or f"Товар {product_id}")
                    description = description_info.get('description', '')
                
                    # Если нет описания из v1, используем базовое
                    if not description:
                        description = f"Артикул: {offer_id}" if offer_id else f"ID: {product_id}"
                
                    # Получаем цену из v5
                    price = self._extract_price_from_v5(prices_data.get(product_id, {}))
                    if price == 0:
                        logger.warning(f"⚠️ Пропускаем товар без цены: {name}")
                        continue
                
                    # Получаем количество
                    quantity = self._extract_quantity(stocks_data.get(product_id, {}))
                    logger.info(f"📦 Итоговое количество для {name}: {quantity}")
                
                    # Очищаем описание от HTML тегов и обрезаем
                    description = self._clean_description(description)
                    if len(description) > 150:
                        description = description[:150] + "..."
                
                    products.append({
                        'product_id': product_id,
                        'offer_id': offer_id,
                        'name': name,
                        'price': price,
                        'description': description,
                        'quantity': quantity
                    })
                    
                    logger.info(f"📦 {name} - {price} ₽ (Остаток: {quantity})")
                
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
    
    def _get_products_descriptions(self, product_ids):
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
                        descriptions_data[product_id] = {
                            'name': description_result.get('name', ''),
                            'description': description_result.get('description', '')
                        }
                        logger.info(f"📝 Получено описание для товара {product_id}")
                else:
                    logger.warning(f"⚠️ Ошибка получения описания для {product_id}: {description_response.status_code}")
            
            logger.info(f"📝 Всего получено описаний: {len(descriptions_data)}")
            return descriptions_data
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения описаний: {e}")
            return {}
    
    def _get_products_prices_v5(self, product_ids):
        """Получает цены товаров через v5/product/info/prices"""
        prices_data = {}
        
        if not product_ids:
            return prices_data
            
        try:
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
    
    def _extract_price_from_v5(self, price_item):
        """Извлекает цену из структуры Ozon v5"""
        if not price_item or not isinstance(price_item, dict):
            return 0
    
        try:
            price_info = price_item.get('price', {})
            
            if not isinstance(price_info, dict):
                return 0
        
            main_price = price_info.get('price')
            if main_price:
                price_int = int(float(main_price))
                if price_int > 0:
                    logger.info(f"✅ Найдена цена: {price_int} ₽")
                    return price_int
        
            old_price = price_info.get('old_price')
            if old_price:
                price_int = int(float(old_price))
                if price_int > 0:
                    logger.info(f"✅ Найдена старая цена: {price_int} ₽")
                    return price_int
        
            return 0
        
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения цена: {e}")
            return 0

    def _get_products_stocks_alternative(self, product_ids):
        """Альтернативный метод получения остатков через v2/products/stocks"""
        stocks_data = {}
        
        if not product_ids:
            return stocks_data
            
        try:
            for i in range(0, len(product_ids), 50):
                batch_ids = product_ids[i:i+50]
                
                info_response = requests.post(
                    "https://api-seller.ozon.ru/v2/products/stocks",
                    headers=self.headers,
                    json={"product_id": batch_ids},
                    timeout=10
                )
                
                if info_response.status_code == 200:
                    info_result = info_response.json()
                    items = info_result.get('result', {}).get('items', [])
                    logger.info(f"📦 Получена информация для {len(items)} товаров через v2")
                    
                    for item in items:
                        product_id = item.get('product_id')
                        if product_id:
                            stock = item.get('stock', 0)
                            fbo_stock = item.get('fbo_stock', 0)
                            fbs_stock = item.get('fbs_stock', 0)
                            
                            available_stock = max(
                                int(stock) if stock else 0,
                                int(fbo_stock) if fbo_stock else 0, 
                                int(fbs_stock) if fbs_stock else 0
                            )
                            
                            stocks_data[product_id] = {
                                'total_stock': available_stock,
                                'stock': stock,
                                'fbo_stock': fbo_stock,
                                'fbs_stock': fbs_stock
                            }
                            
                            logger.info(f"✅ Доступный остаток для {product_id}: {available_stock}")
                else:
                    logger.warning(f"⚠️ Ошибка получения информации v2: {info_response.status_code}")
                    for product_id in batch_ids:
                        stocks_data[product_id] = {'total_stock': 10}
            
            return stocks_data
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения остатков v2: {e}")
            for product_id in product_ids:
                stocks_data[product_id] = {'total_stock': 10}
            return stocks_data

    def _extract_quantity(self, stock_item):
        """Извлекает количество из структуры остатков"""
        try:
            if not stock_item:
                logger.warning("⚠️ Нет данных об остатках, используем значение по умолчанию: 10")
                return 10
        
            total_stock = stock_item.get('total_stock', 10)
            logger.info(f"📊 Извлекаем количество: {total_stock}")
            
            return max(1, total_stock)
        
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения количества: {e}")
            return 10

    def _clean_description(self, description):
        """Очищает описание от HTML тегов"""
        if not description:
            return ""
        
        clean_text = re.sub(r'<br\s*/?>', '\n', description)
        clean_text = re.sub(r'<[^>]+>', '', clean_text)
        clean_text = re.sub(r'\n\s*\n', '\n', clean_text)
        clean_text = clean_text.strip()
        
        return clean_text

    def create_product_links(self, cart_items):
        """Создает ссылки на страницы товаров Ozon"""
        product_links = []
        
        for product_index, quantity in cart_items.items():
            product = products_cache.get(int(product_index))
            if product and product.get('product_id'):
                # Создаем ссылку на страницу товара в Ozon
                product_url = f"https://www.ozon.ru/product/{product['product_id']}/"
                product_links.append({
                    'name': product['name'],
                    'url': product_url,
                    'quantity': quantity,
                    'price': product['price']
                })
        
        return product_links

# Инициализация API
ozon_api = OzonSellerAPI()

async def checkout(query, context):
    """Создает список товаров с ссылками для ручного добавления в корзину"""
    cart = context.user_data.get('cart', {})
    
    if not cart:
        await query.answer("❌ Корзина пуста", show_alert=True)
        return
    
    # Создаем ссылки на товары
    product_links = ozon_api.create_product_links(cart)
    
    if not product_links:
        await query.answer("❌ Ошибка создания ссылок на товары", show_alert=True)
        return
    
    # Считаем общую сумму и количество товаров
    total = 0
    items_count = 0
    cart_items_text = ""
    
    for link_info in product_links:
        item_total = link_info['price'] * link_info['quantity']
        total += item_total
        items_count += link_info['quantity']
        product_name = link_info['name']
        if len(product_name) > 30:
            product_name = product_name[:27] + "..."
        cart_items_text += f"• {product_name} - {link_info['quantity']} шт. = {item_total} ₽\n"

    # Формируем инструкцию
    instruction_text = """
📋 *Инструкция по оформлению заказа:*

1. *Поочередно перейдите по ссылкам ниже*
2. *На каждой странице товара:*
   - Нажмите кнопку «В корзину»
   - Установите нужное количество
3. *После добавления всех товаров:*
   - Перейдите в корзину Ozon
   - Завершите оформление заказа

🛒 *Ссылки на товары:*
"""

    # Создаем сообщение со ссылками
    message_text = f"""
✅ *Ваш заказ готов к оформлению!*

{cart_items_text}
💰 *Общая сумма:* {total} ₽
📊 *Всего товаров:* {items_count} шт.

{instruction_text}
"""
    
    # Создаем клавиатуру со ссылками на товары
    keyboard = []
    for i, link_info in enumerate(product_links, 1):
        product_name = link_info['name']
        if len(product_name) > 30:
            product_name = product_name[:27] + "..."
        keyboard.append([InlineKeyboardButton(
            f"📦 {i}. {product_name} ({link_info['quantity']} шт.)", 
            url=link_info['url']
        )])
    
    # Добавляем вспомогательные кнопки
    keyboard.extend([
        [InlineKeyboardButton("🛒 Перейти в корзину Ozon", url="https://www.ozon.ru/cart")],
        [InlineKeyboardButton("📦 Мои заказы", callback_data="view_orders")],
        [InlineKeyboardButton("🛍️ Продолжить покупки", callback_data="view_products"),
         InlineKeyboardButton("🗑️ Очистить корзину", callback_data="clear_cart")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Сохраняем заказ в историю
    if 'orders' not in context.user_data:
        context.user_data['orders'] = []
    
    new_order = {
        'total': total,
        'items_count': items_count,
        'created_at': datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        'customer_name': query.from_user.first_name,
        'status': 'ожидает оформления в Ozon',
        'product_links': product_links
    }
    
    context.user_data['orders'].append(new_order)
    
    await query.edit_message_text(message_text, reply_markup=reply_markup, parse_mode='Markdown')

async def clear_cart(query, context):
    """Очищает корзину полностью"""
    context.user_data['cart'] = {}
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Начать покупки", callback_data="view_products")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("🗑️ *Корзина очищена*", reply_markup=reply_markup, parse_mode='Markdown')

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
            [InlineKeyboardButton("🛒 Корзина", callback_data="view_cart")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(success_text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        error_text = """
❌ *Не удалось обновить товары*

Попробуйте позже или проверьте настройки API.
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="refresh_products")],
            [InlineKeyboardButton("🛍️ Использовать текущий список", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(error_text, reply_markup=reply_markup, parse_mode='Markdown')

async def load_real_products():
    """Загружает только реальные товары из Ozon API"""
    global products_cache
    
    logger.info("🔄 Загрузка реальных товаров из Ozon...")
    
    if not OZON_CLIENT_ID or not OZON_API_KEY:
        logger.error("❌ API ключи не настроены!")
        products_cache = {}
        return {}
    
    products_data = ozon_api.get_products_with_prices(limit=50)
    
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
            quantity = item.get('quantity', 0)
            
            if price == 0:
                continue
            
            if not description:
                description = f"Артикул: {offer_id}" if offer_id else f"ID: {product_id}"
            
            product_key = product_counter
            
            products[product_key] = {
                'product_id': product_id,
                'offer_id': offer_id,
                'name': name,
                'price': price,
                'description': description,
                'quantity': quantity
            }
            
            logger.info(f"✅ Товар {product_counter}: {name} - {price} ₽ (Остаток: {quantity})")
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

🛒 *Как работает оформление заказа:*
1. Выбирайте товары в боте
2. Добавляйте в корзину
3. Получайте ссылки на страницы товаров Ozon
4. Самостоятельно добавляйте товары в корзину Ozon
5. Завершайте покупку на официальном сайте

Используйте кнопки ниже для навигации:
"""
    
    keyboard = [
        [InlineKeyboardButton("🛍️ Смотреть товары", callback_data="view_products")],
        [InlineKeyboardButton("🛒 Корзина", callback_data="view_cart"),
         InlineKeyboardButton("📦 Мои заказы", callback_data="view_orders")],
        [InlineKeyboardButton("🔄 Обновить товары", callback_data="refresh_products")],
        [InlineKeyboardButton("📱 Личный кабинет Ozon", url="https://www.ozon.ru/my/orderlist/")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

# ДОБАВЛЯЕМ НЕДОСТАЮЩУЮ ФУНКЦИЮ refresh_products
async def refresh_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /refresh для обновления товаров"""
    await update.message.reply_text("🔄 Обновляем список реальных товаров...")
    products_count_before = len(products_cache)
    await load_real_products()
    products_count_after = len(products_cache)
    
    if products_count_after > 0:
        await update.message.reply_text(
            f"✅ Реальные товары обновлены!\n"
            f"📦 Доступно товаров: {products_count_after}"
        )
    else:
        await update.message.reply_text(
            "❌ Не удалось загрузить реальные товары.\n"
            "Проверьте настройки API ключей Ozon."
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback запросов от кнопок"""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "view_products":
        await show_products(query, context)
    elif callback_data == "view_cart":
        await show_cart(query, context)
    elif callback_data == "view_orders":
        await show_orders(query, context)
    elif callback_data == "refresh_products":
        await refresh_products_callback(query, context)
    elif callback_data == "checkout":
        await checkout(query, context)
    elif callback_data == "clear_cart":
        await clear_cart(query, context)    
    elif callback_data.startswith("product_"):
        await handle_product_action(query, context, callback_data)

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
         InlineKeyboardButton("🛒 Корзина", callback_data="view_cart")]       
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
    """Показывает корзину пользователя"""
    cart = context.user_data.get('cart', {})
    
    if not cart:
        cart_text = "🛒 *Ваша корзина пуста*"
        
        keyboard = [
            [InlineKeyboardButton("🛍️ Начать покупки", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(cart_text, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    total = 0
    cart_text = "🛒 *Ваша корзина:*\n\n"
    
    for product_index, quantity in cart.items():
        product = products_cache.get(int(product_index))
        if product:
            item_total = product['price'] * quantity
            total += item_total
            product_name = product['name']
            if len(product_name) > 50:
                product_name = product_name[:47] + "..."
            cart_text += f"• {product_name}\n  {quantity} × {product['price']} ₽ = {item_total} ₽\n"
    
    cart_text += f"\n💵 *Итого:* {total} ₽"
    cart_text += "\n\n🛒 *Для оформления заказа нажмите кнопку ниже*"
    
    keyboard = [
        [InlineKeyboardButton("💰 Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton("🛍️ Продолжить покупки", callback_data="view_products"),
         InlineKeyboardButton("🗑️ Очистить корзину", callback_data="clear_cart")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(cart_text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_orders(query, context):
    """Показывает заказы пользователя"""
    orders = context.user_data.get('orders', [])
    
    if not orders:
        orders_text = "📦 *У вас пока нет заказов*"
        
        keyboard = [
            [InlineKeyboardButton("🛍️ Начать покупки", callback_data="view_products")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(orders_text, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    orders_text = "📦 *История ваших заказов:*\n\n"
    
    for i, order in enumerate(orders, 1):
        orders_text += f"*Заказ #{i}:*\n"
        orders_text += f"💰 Сумма: {order['total']} ₽\n"
        orders_text += f"📅 Дата: {order['created_at']}\n"
        orders_text += f"📦 Товаров: {order['items_count']} шт.\n"
        orders_text += f"👤 Получатель: {order['customer_name']}\n"
        orders_text += f"📊 Статус: {order.get('status', 'создан')}\n"
        orders_text += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    keyboard = [
        [InlineKeyboardButton("🛒 Корзина", callback_data="view_cart")],
        [InlineKeyboardButton("🛍️ К товарам", callback_data="view_products")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(orders_text, reply_markup=reply_markup, parse_mode='Markdown')

async def preload_products():
    """Предзагрузка товаров при запуске"""
    logger.info("🔄 Предзагрузка реальных товаров...")
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
    application.add_handler(CommandHandler("refresh", refresh_products))  # Теперь эта функция определена
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    logger.info("🔄 Загрузка реальных товаров из Ozon...")
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(preload_products())
    
    logger.info("🛍️ Ozon Client Bot запущен!")
    application.run_polling()

if __name__ == '__main__':
    main()

import os
import requests
import json

print("🔍 Тестируем Ozon API в Railway...")
print("=" * 50)

# Получаем переменные из Railway
OZON_API_KEY = os.environ.get('OZON_API_KEY')
OZON_CLIENT_ID = os.environ.get('OZON_CLIENT_ID')

print(f"🔑 Client ID: {'✅ Есть' if OZON_CLIENT_ID else '❌ НЕТ'}")
print(f"🔑 API Key: {'✅ Есть' if OZON_API_KEY else '❌ НЕТ'}")

if not OZON_API_KEY or not OZON_CLIENT_ID:
    print("❌ Ошибка: Добавьте OZON_API_KEY и OZON_CLIENT_ID в Railway Variables!")
    exit(1)

# Настройки API
headers = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

def test_api(endpoint_name, url, payload):
    """Тестирует endpoint Ozon API"""
    print(f"\n🎯 Тестируем: {endpoint_name}")
    print(f"   📡 URL: {url}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"   📊 Статус: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"   ✅ УСПЕХ!")
            
            # Анализируем ответ
            if 'result' in data:
                result = data['result']
                if 'items' in result:
                    print(f"   📦 Товаров: {len(result['items'])}")
                elif 'postings' in result:
                    print(f"   🚚 Заказов: {len(result['postings'])}")
                else:
                    print(f"   📋 Данные: {str(result)[:100]}...")
            return True
            
        elif response.status_code == 403:
            print("   ❌ ОШИБКА: Access Denied - проверьте права API ключа")
            print(f"   💬 Ответ: {response.text[:200]}")
        elif response.status_code == 401:
            print("   ❌ ОШИБКА: Invalid API Key - проверьте Client ID и API Key")
        else:
            print(f"   ❌ ОШИБКА: {response.status_code}")
            print(f"   💬 Ответ: {response.text[:200]}")
            
        return False
        
    except requests.exceptions.Timeout:
        print("   ⏰ Таймаут запроса")
        return False
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

# Запускаем тесты
print("\n" + "="*50)
print("🚀 ЗАПУСК ТЕСТОВ OZON API")
print("="*50)

# Тест 1: Список товаров
test_api(
    "Список товаров",
    "https://api-seller.ozon.ru/v2/product/list",
    {"limit": 10, "filter": {"visibility": "ALL"}}
)

# Тест 2: FBS заказы
test_api(
    "FBS заказы",
    "https://api-seller.ozon.ru/v2/posting/fbs/list", 
    {"limit": 10}
)

# Тест 3: Информация о товарах
test_api(
    "Информация о товарах",
    "https://api-seller.ozon.ru/v2/product/info/list",
    {"product_id": []}
)

print("\n" + "="*50)
print("🏁 ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
print("="*50)

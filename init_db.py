import os
import sys
from app import app
from models import db, MenuItem, Inventory, Employee, Shift, Reservation, Order, OrderItem, FinancialRecord, SocialMediaPost

def init_database():
    """Tworzy wszystkie tabele w bazie danych"""
    with app.app_context():
        print("=" * 60)
        print("🔧 INICJALIZACJA BAZY DANYCH")
        print("=" * 60)
        
        try:
            # Tworzenie wszystkich tabel
            print("\n📋 Tworzenie tabel...")
            db.create_all()
            
            print("\n✅ SUKCES! Wszystkie tabele zostały utworzone:")
            print("   - menu_items")
            print("   - inventory")
            print("   - employees")
            print("   - shifts")
            print("   - reservations")
            print("   - orders")
            print("   - order_items")
            print("   - financial_records")
            print("   - social_media_posts")
            print("\n" + "=" * 60)
            print("✅ Baza danych jest gotowa do użycia!")
            print("=" * 60)
            
        except Exception as e:
            print(f"\n❌ BŁĄD podczas tworzenia tabel: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    init_database()
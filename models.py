from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Index

db = SQLAlchemy()

# ===== MENU ITEMS =====
class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(100))
    cost_price = db.Column(db.Numeric(10, 2))
    popularity_score = db.Column(db.Integer, default=0)
    times_ordered = db.Column(db.Integer, default=0)
    last_ordered = db.Column(db.DateTime)
    profit_margin = db.Column(db.Numeric(5, 2))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    order_items = db.relationship('OrderItem', backref='menu_item', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'price': float(self.price),
            'category': self.category,
            'cost_price': float(self.cost_price) if self.cost_price else None,
            'popularity_score': self.popularity_score,
            'times_ordered': self.times_ordered,
            'last_ordered': self.last_ordered.isoformat() if self.last_ordered else None,
            'profit_margin': float(self.profit_margin) if self.profit_margin else None,
            'is_active': self.is_active
        }


# ===== INVENTORY =====
class Inventory(db.Model):
    __tablename__ = 'inventory'
    
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit = db.Column(db.String(50))
    supplier = db.Column(db.String(200))
    purchase_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    cost_per_unit = db.Column(db.Numeric(10, 2))
    minimum_stock_level = db.Column(db.Numeric(10, 2))
    category = db.Column(db.String(100))
    status = db.Column(db.String(50), default='available')
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_name': self.product_name,
            'quantity': float(self.quantity),
            'unit': self.unit,
            'supplier': self.supplier,
            'purchase_date': self.purchase_date.isoformat() if self.purchase_date else None,
            'expiry_date': self.expiry_date.isoformat() if self.expiry_date else None,
            'cost_per_unit': float(self.cost_per_unit) if self.cost_per_unit else None,
            'minimum_stock_level': float(self.minimum_stock_level) if self.minimum_stock_level else None,
            'category': self.category,
            'status': self.status
        }


# ===== EMPLOYEES =====
class Employee(db.Model):
    __tablename__ = 'employees'
    
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    position = db.Column(db.String(100))
    hourly_rate = db.Column(db.Numeric(10, 2))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(200))
    hire_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    
    shifts = db.relationship('Shift', backref='employee', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': f"{self.first_name} {self.last_name}",
            'position': self.position,
            'hourly_rate': float(self.hourly_rate) if self.hourly_rate else None,
            'phone': self.phone,
            'email': self.email,
            'hire_date': self.hire_date.isoformat() if self.hire_date else None,
            'is_active': self.is_active
        }


# ===== SHIFTS =====
class Shift(db.Model):
    __tablename__ = 'shifts'
    
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False)
    shift_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    position = db.Column(db.String(100))
    status = db.Column(db.String(50), default='scheduled')
    notes = db.Column(db.Text)
    
    def to_dict(self):
        return {
            'id': self.id,
            'employee_id': self.employee_id,
            'employee_name': f"{self.employee.first_name} {self.employee.last_name}" if self.employee else None,
            'shift_date': self.shift_date.isoformat(),
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat(),
            'position': self.position,
            'status': self.status,
            'notes': self.notes
        }


# ===== RESERVATIONS =====
class Reservation(db.Model):
    __tablename__ = 'reservations'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(200))
    party_size = db.Column(db.Integer, nullable=False)
    reservation_date = db.Column(db.Date, nullable=False)
    reservation_time = db.Column(db.Time, nullable=False)
    table_number = db.Column(db.String(20))
    status = db.Column(db.String(50), default='confirmed')
    special_requests = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_name': self.customer_name,
            'phone': self.phone,
            'email': self.email,
            'party_size': self.party_size,
            'reservation_date': self.reservation_date.isoformat(),
            'reservation_time': self.reservation_time.isoformat(),
            'table_number': self.table_number,
            'status': self.status,
            'special_requests': self.special_requests,
            'created_at': self.created_at.isoformat()
        }


# ===== ORDERS =====
class Order(db.Model):
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    order_time = db.Column(db.Time, nullable=False)
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50))
    status = db.Column(db.String(50), default='pending')
    table_number = db.Column(db.String(20))
    
    order_items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_date': self.order_date.isoformat(),
            'order_time': self.order_time.isoformat(),
            'total_amount': float(self.total_amount),
            'payment_method': self.payment_method,
            'status': self.status,
            'table_number': self.table_number,
            'items': [item.to_dict() for item in self.order_items]
        }


# ===== ORDER ITEMS =====
class OrderItem(db.Model):
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_items.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    
    def to_dict(self):
        return {
            'id': self.id,
            'order_id': self.order_id,
            'menu_item_id': self.menu_item_id,
            'menu_item_name': self.menu_item.name if self.menu_item else None,
            'quantity': self.quantity,
            'price': float(self.price)
        }


# ===== FINANCIAL RECORDS =====
class FinancialRecord(db.Model):
    __tablename__ = 'financial_records'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    revenue = db.Column(db.Numeric(10, 2), default=0)
    costs = db.Column(db.Numeric(10, 2), default=0)
    net_profit = db.Column(db.Numeric(10, 2))
    category = db.Column(db.String(100))
    description = db.Column(db.Text)
    payment_method = db.Column(db.String(50))
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'revenue': float(self.revenue),
            'costs': float(self.costs),
            'net_profit': float(self.net_profit) if self.net_profit else None,
            'category': self.category,
            'description': self.description,
            'payment_method': self.payment_method
        }


# ===== SOCIAL MEDIA POSTS =====
class SocialMediaPost(db.Model):
    __tablename__ = 'social_media_posts'
    
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50))
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500))
    status = db.Column(db.String(50), default='draft')
    scheduled_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_by = db.Column(db.String(100))
    
    def to_dict(self):
        return {
            'id': self.id,
            'platform': self.platform,
            'content': self.content,
            'image_url': self.image_url,
            'status': self.status,
            'scheduled_date': self.scheduled_date.isoformat() if self.scheduled_date else None,
            'created_at': self.created_at.isoformat(),
            'approved_by': self.approved_by
        }


# Indeksy dla optymalizacji
Index('idx_menu_items_category', MenuItem.category)
Index('idx_menu_items_active', MenuItem.is_active)
Index('idx_inventory_expiry', Inventory.expiry_date)
Index('idx_inventory_status', Inventory.status)
Index('idx_shifts_date', Shift.shift_date)
Index('idx_reservations_date', Reservation.reservation_date)
Index('idx_orders_date', Order.order_date)
Index('idx_financial_date', FinancialRecord.date)

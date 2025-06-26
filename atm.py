import sqlite3
import os
import sys
import getpass
import csv
from datetime import datetime

DB_NAME = 'atm.db'
LOG_FILE = 'transactions.log'
ATM_CASH_LIMIT = 200000  # Total cash ATM can hold
DAILY_WITHDRAWAL_LIMIT = 50000  # Per account daily withdrawal limit
FAST_CASH_OPTIONS = [500, 1000, 5000]
MINI_STATEMENT_COUNT = 5

class Database:
    """
    Handles all database operations for accounts and transactions.
    """
    def __init__(self, db_name=DB_NAME):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    account_no TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    card_no TEXT UNIQUE NOT NULL,
                    pin TEXT NOT NULL,
                    balance INTEGER NOT NULL,
                    blocked INTEGER DEFAULT 0,
                    failed_attempts INTEGER DEFAULT 0
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_no TEXT,
                    type TEXT,
                    amount INTEGER,
                    date TEXT,
                    details TEXT
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS atm (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    total_cash INTEGER
                )
            ''')
            # Initialize ATM cash if not present
            cur = self.conn.execute('SELECT * FROM atm WHERE id = 1')
            if not cur.fetchone():
                self.conn.execute('INSERT INTO atm (id, total_cash) VALUES (1, ?)', (ATM_CASH_LIMIT,))

    def add_account(self, account_no, name, card_no, pin, balance):
        with self.conn:
            self.conn.execute('''
                INSERT INTO accounts (account_no, name, card_no, pin, balance) VALUES (?, ?, ?, ?, ?)
            ''', (account_no, name, card_no, pin, balance))

    def get_account_by_card(self, card_no):
        cur = self.conn.execute('SELECT * FROM accounts WHERE card_no = ?', (card_no,))
        return cur.fetchone()

    def get_account_by_no(self, account_no):
        cur = self.conn.execute('SELECT * FROM accounts WHERE account_no = ?', (account_no,))
        return cur.fetchone()

    def update_account(self, account_no, **kwargs):
        keys = ', '.join([f'{k} = ?' for k in kwargs])
        values = list(kwargs.values())
        values.append(account_no)
        with self.conn:
            self.conn.execute(f'UPDATE accounts SET {keys} WHERE account_no = ?', values)

    def add_transaction(self, account_no, type_, amount, details=''):
        with self.conn:
            self.conn.execute('''
                INSERT INTO transactions (account_no, type, amount, date, details) VALUES (?, ?, ?, ?, ?)
            ''', (account_no, type_, amount, datetime.now().isoformat(), details))

    def get_transactions(self, account_no, limit=MINI_STATEMENT_COUNT):
        cur = self.conn.execute('''
            SELECT type, amount, date, details FROM transactions WHERE account_no = ? ORDER BY date DESC LIMIT ?
        ''', (account_no, limit))
        return cur.fetchall()

    def get_balance(self, account_no):
        cur = self.conn.execute('SELECT balance FROM accounts WHERE account_no = ?', (account_no,))
        row = cur.fetchone()
        return row[0] if row else None

    def update_balance(self, account_no, new_balance):
        with self.conn:
            self.conn.execute('UPDATE accounts SET balance = ? WHERE account_no = ?', (new_balance, account_no))

    def get_atm_cash(self):
        cur = self.conn.execute('SELECT total_cash FROM atm WHERE id = 1')
        return cur.fetchone()[0]

    def update_atm_cash(self, new_cash):
        with self.conn:
            self.conn.execute('UPDATE atm SET total_cash = ? WHERE id = 1', (new_cash,))

    def get_all_accounts(self):
        cur = self.conn.execute('SELECT * FROM accounts')
        return cur.fetchall()

    def get_all_transactions(self):
        cur = self.conn.execute('SELECT * FROM transactions')
        return cur.fetchall()

class Logger:
    """
    Handles logging of transactions and errors to a file.
    """
    def __init__(self, log_file=LOG_FILE):
        self.log_file = log_file

    def log(self, message):
        with open(self.log_file, 'a') as f:
            f.write(f"{datetime.now().isoformat()} - {message}\n")
            

    def log_transaction(self, account_no, type_, amount, details=''):
        with open(self.log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([datetime.now().isoformat(), account_no, type_, amount, details])

class Account:
    """
    Represents a bank account and provides account operations.
    """
    def __init__(self, db, logger, account_row):
        self.db = db
        self.logger = logger
        self.account_no = account_row[0]
        self.name = account_row[1]
        self.card_no = account_row[2]
        self.pin = account_row[3]
        self.balance = account_row[4]
        self.blocked = account_row[5]
        self.failed_attempts = account_row[6]

    def view_balance(self):
        print(f"\nCurrent Balance: ₹{self.balance}")

    def view_details(self):
        print(f"\nAccount Number: {self.account_no}\nName: {self.name}\nCard Number: {self.card_no}")

    def view_mini_statement(self):
        print("\nMini Statement (Last Transactions):")
        transactions = self.db.get_transactions(self.account_no)
        for t in transactions:
            print(f"{t[2][:19]} | {t[0]} | ₹{t[1]} | {t[3]}")

    def change_pin(self):
        old_pin = getpass.getpass("Enter current PIN: ")
        if old_pin != self.pin:
            print("Incorrect current PIN.")
            return
        new_pin = getpass.getpass("Enter new PIN: ")
        confirm_pin = getpass.getpass("Confirm new PIN: ")
        if new_pin != confirm_pin:
            print("PINs do not match.")
            return
        self.db.update_account(self.account_no, pin=new_pin)
        self.pin = new_pin
        print("PIN changed successfully.")
        self.logger.log(f"PIN changed for account {self.account_no}")

class ATM:
    """
    Main ATM class handling authentication, transactions, and admin features.
    """
    def __init__(self):
        self.db = Database()
        self.logger = Logger()
        self.current_account = None

    def authenticate(self):
        card_no = input("Enter Card Number: ")
        account_row = self.db.get_account_by_card(card_no)
        if not account_row:
            print("Card not found.")
            self.logger.log(f"Failed login attempt: Card {card_no} not found.")
            return False
        if account_row[5]:
            print("This card is blocked due to multiple failed attempts.")
            self.logger.log(f"Blocked card login attempt: {card_no}")
            return False
        for attempt in range(3):
            pin = getpass.getpass("Enter PIN: ")
            if pin == account_row[3]:
                self.db.update_account(account_row[0], failed_attempts=0)
                self.current_account = Account(self.db, self.logger, account_row)
                return True
            else:
                print("Incorrect PIN.")
                self.db.update_account(account_row[0], failed_attempts=account_row[6]+1)
                if account_row[6]+1 >= 3:
                    self.db.update_account(account_row[0], blocked=1)
                    print("Card blocked after 3 failed attempts.")
                    self.logger.log(f"Card {card_no} blocked after 3 failed attempts.")
                    return False
        return False

    def main_menu(self):
        while True:
            print("\nATM Main Menu:")
            print("1. View Balance")
            print("2. Mini Statement")
            print("3. View Account Details")
            print("4. Withdraw Cash")
            print("5. Deposit Cash")
            print("6. Transfer Funds")
            print("7. Fast Cash")
            print("8. Change PIN")
            print("9. Exit")
            choice = input("Select an option: ")
            if not self.current_account:
                print("No account is currently logged in.")
                return
            if choice == '1':
                self.current_account.view_balance()
            elif choice == '2':
                self.current_account.view_mini_statement()
            elif choice == '3':
                self.current_account.view_details()
            elif choice == '4':
                self.withdraw_cash()
            elif choice == '5':
                self.deposit_cash()
            elif choice == '6':
                self.transfer_funds()
            elif choice == '7':
                self.fast_cash()
            elif choice == '8':
                self.current_account.change_pin()
            elif choice == '9':
                print("Thank you for using the ATM. Goodbye!")
                self.current_account = None
                break
            else:
                print("Invalid option. Try again.")

    def withdraw_cash(self):
        if not self.current_account:
            print("No account is currently logged in.")
            return
        amount = input("Enter amount to withdraw: ")
        try:
            amount = int(amount)
        except ValueError:
            print("Invalid amount.")
            return
        if amount <= 0:
            print("Amount must be positive.")
            return
        if amount > self.current_account.balance:
            print("Insufficient balance.")
            return
        if amount > DAILY_WITHDRAWAL_LIMIT:
            print(f"Exceeds daily withdrawal limit of ₹{DAILY_WITHDRAWAL_LIMIT}.")
            return
        atm_cash = self.db.get_atm_cash()
        if amount > atm_cash:
            print("ATM does not have enough cash.")
            return
        new_balance = self.current_account.balance - amount
        self.db.update_balance(self.current_account.account_no, new_balance)
        self.db.update_atm_cash(atm_cash - amount)
        self.db.add_transaction(self.current_account.account_no, 'Withdraw', amount)
        self.logger.log_transaction(self.current_account.account_no, 'Withdraw', amount)
        self.current_account.balance = new_balance
        print(f"Withdrawn ₹{amount}. New balance: ₹{new_balance}")

    def deposit_cash(self):
        if not self.current_account:
            print("No account is currently logged in.")
            return
        amount = input("Enter amount to deposit: ")
        try:
            amount = int(amount)
        except ValueError:
            print("Invalid amount.")
            return
        if amount <= 0:
            print("Amount must be positive.")
            return
        atm_cash = self.db.get_atm_cash()
        if atm_cash + amount > ATM_CASH_LIMIT:
            print("ATM cannot accept this much cash. Exceeds ATM limit.")
            return
        new_balance = self.current_account.balance + amount
        self.db.update_balance(self.current_account.account_no, new_balance)
        self.db.update_atm_cash(atm_cash + amount)
        self.db.add_transaction(self.current_account.account_no, 'Deposit', amount)
        self.logger.log_transaction(self.current_account.account_no, 'Deposit', amount)
        self.current_account.balance = new_balance
        print(f"Deposited ₹{amount}. New balance: ₹{new_balance}")

    def transfer_funds(self):
        if not self.current_account:
            print("No account is currently logged in.")
            return
        target_acc = input("Enter target account number: ")
        target_row = self.db.get_account_by_no(target_acc)
        if not target_row:
            print("Target account not found.")
            return
        amount = input("Enter amount to transfer: ")
        try:
            amount = int(amount)
        except ValueError:
            print("Invalid amount.")
            return
        if amount <= 0:
            print("Amount must be positive.")
            return
        if amount > self.current_account.balance:
            print("Insufficient balance.")
            return
        new_balance = self.current_account.balance - amount
        target_balance = target_row[4] + amount
        self.db.update_balance(self.current_account.account_no, new_balance)
        self.db.update_balance(target_acc, target_balance)
        self.db.add_transaction(self.current_account.account_no, 'Transfer Out', amount, f"To {target_acc}")
        self.db.add_transaction(target_acc, 'Transfer In', amount, f"From {self.current_account.account_no}")
        self.logger.log_transaction(self.current_account.account_no, 'Transfer Out', amount, f"To {target_acc}")
        self.logger.log_transaction(target_acc, 'Transfer In', amount, f"From {self.current_account.account_no}")
        self.current_account.balance = new_balance
        print(f"Transferred ₹{amount} to {target_acc}. New balance: ₹{new_balance}")

    def fast_cash(self):
        if not self.current_account:
            print("No account is currently logged in.")
            return
        print("Fast Cash Options:")
        for idx, amt in enumerate(FAST_CASH_OPTIONS, 1):
            print(f"{idx}. ₹{amt}")
        choice = input("Select option: ")
        try:
            idx = int(choice) - 1
            amount = FAST_CASH_OPTIONS[idx]
        except (ValueError, IndexError):
            print("Invalid option.")
            return
        self.withdraw_cash_amount(amount)

    def withdraw_cash_amount(self, amount):
        if not self.current_account:
            print("No account is currently logged in.")
            return
        if amount > self.current_account.balance:
            print("Insufficient balance.")
            return
        if amount > DAILY_WITHDRAWAL_LIMIT:
            print(f"Exceeds daily withdrawal limit of ₹{DAILY_WITHDRAWAL_LIMIT}.")
            return
        atm_cash = self.db.get_atm_cash()
        if amount > atm_cash:
            print("ATM does not have enough cash.")
            return
        new_balance = self.current_account.balance - amount
        self.db.update_balance(self.current_account.account_no, new_balance)
        self.db.update_atm_cash(atm_cash - amount)
        self.db.add_transaction(self.current_account.account_no, 'Fast Cash', amount)
        self.logger.log_transaction(self.current_account.account_no, 'Fast Cash', amount)
        self.current_account.balance = new_balance
        print(f"Withdrawn ₹{amount}. New balance: ₹{new_balance}")

    # Admin features (optional)
    def admin_menu(self):
        print("\nAdmin Menu:")
        print("1. Load Cash into ATM")
        print("2. View ATM Total Cash")
        print("3. View Transaction Logs")
        print("4. Exit Admin Menu")
        while True:
            choice = input("Select an option: ")
            if choice == '1':
                self.load_cash()
            elif choice == '2':
                print(f"ATM Total Cash: ₹{self.db.get_atm_cash()}")
            elif choice == '3':
                self.view_logs()
            elif choice == '4':
                break
            else:
                print("Invalid option.")

    def load_cash(self):
        amount = input("Enter amount to load into ATM: ")
        try:
            amount = int(amount)
        except ValueError:
            print("Invalid amount.")
            return
        if amount <= 0:
            print("Amount must be positive.")
            return
        atm_cash = self.db.get_atm_cash()
        if atm_cash + amount > ATM_CASH_LIMIT:
            print("Exceeds ATM cash limit.")
            return
        self.db.update_atm_cash(atm_cash + amount)
        print(f"Loaded ₹{amount} into ATM. New total: ₹{atm_cash + amount}")
        self.logger.log(f"Admin loaded ₹{amount} into ATM.")

    def view_logs(self):
        if not os.path.exists(LOG_FILE):
            print("No logs found.")
            return
        with open(LOG_FILE, 'r') as f:
            print(f.read())

    def run(self):
        print("Welcome to the ATM CLI System!")
        while True:
            print("\n1. User Login\n2. Admin Menu\n3. Exit")
            choice = input("Select an option: ")
            if choice == '1':
                if self.authenticate():
                    self.main_menu()
            elif choice == '2':
                self.admin_menu()
            elif choice == '3':
                print("Exiting...")
                break
            else:
                print("Invalid option.")

# Sample database population for demo
if __name__ == "__main__":
    # Populate sample data if not present
    db = Database()
    logger = Logger()
    if not db.get_account_by_card('1234567890'):
        db.add_account('1001', 'Alice', '1234567890', '1111', 100000)
    if not db.get_account_by_card('9876543210'):
        db.add_account('1002', 'Bob', '9876543210', '2222', 50000)
    atm = ATM()
    atm.run() 
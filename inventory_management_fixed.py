"""
Inventory Management App (System)
- Add, update, and manage products
- Record sales and update stock
- Search products and check low stock
- Save data, view inventory, and exit
"""

import json
import os
import re

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory.json")
LOW_STOCK_THRESHOLD = 5
DEFAULT_CURRENCY = "$"

# Typing 'exit' or 'cancel' at any prompt abandons the current action entirely.
ABANDON_WORDS = {"exit", "cancel"}
# Typing 'back' returns to the previous question within a multi-step form
# (or abandons the action if there's no previous question to go back to).
STEP_BACK_WORD = "back"


class BackToMenu(Exception):
    """Raised when the user wants to abandon the current action and
    return to the main menu, without applying any partial changes."""
    pass


class StepBack(Exception):
    """Raised when the user wants to return to the previous question
    within the current multi-step form."""
    pass


def ask(prompt, allow_step_back=False):
    """Get a line of input.
    - 'exit' or 'cancel' always abandon the current action (-> BackToMenu).
    - 'back': if allow_step_back is True, returns to the previous question
      in this form (-> StepBack); otherwise also abandons (-> BackToMenu),
      since there's no previous question to go back to.
    """
    raw = input(prompt)
    word = raw.strip().lower()
    if word in ABANDON_WORDS:
        raise BackToMenu
    if word == STEP_BACK_WORD:
        if allow_step_back:
            raise StepBack
        raise BackToMenu
    return raw


def load_data():
    """Load inventory from disk if it exists, otherwise start empty."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print("Warning: data file was corrupted or empty. Starting fresh.")
                return {}
        # Backward compatibility: older saved files may not have a "currency" field.
        for details in data.values():
            details.setdefault("currency", DEFAULT_CURRENCY)
        return data
    return {}


def save_data(inventory):
    """Write the current inventory to disk as JSON."""
    with open(DATA_FILE, "w") as f:
        json.dump(inventory, f, indent=4)
    print("Data saved.")


def normalize_price_string(raw):
    """Normalize a price string that may use ',' and/or '.' as thousands
    and/or decimal separators. The rightmost separator is treated as the
    decimal point ONLY if it is followed by exactly 1 or 2 digits (a
    plausible cents amount); every other separator is treated as a
    thousands separator and discarded. Examples:
        '1,800.00' -> '1800.00'   '1.800,00' -> '1800.00'
        '1,800,00' -> '1800.00'   '1.800.00' -> '1800.00'
        '1,800'    -> '1800'      '1800'     -> '1800'
    Returns a plain numeric string, or None if no digits were found."""
    s = re.sub(r"[^0-9,.\-]", "", raw)
    if not s or not re.search(r"\d", s):
        return None

    last_sep_pos = max(s.rfind(","), s.rfind("."))
    if last_sep_pos == -1:
        return s

    after = s[last_sep_pos + 1:]
    before = s[:last_sep_pos]
    if after.isdigit() and 1 <= len(after) <= 2:
        integer_part = re.sub(r"[,.]", "", before) or "0"
        return f"{integer_part}.{after}"
    return re.sub(r"[,.]", "", s)


def parse_int(raw):
    """Parse a whole number from a string, tolerating extra text/symbols
    and thousands separators (',' or '.'), e.g. '1,000 units' -> 1000."""
    s = re.sub(r"[^0-9\-]", "", raw)
    match = re.search(r"-?\d+", s)
    if not match:
        return None
    return int(match.group())


def parse_price(raw):
    """Parse a price from a string, tolerating currency symbols, spaces,
    and mixed thousands/decimal separators, e.g. '$1,800.00' -> 1800.0,
    '1.800,00' -> 1800.0, '1,800,00' -> 1800.0."""
    normalized = normalize_price_string(raw)
    if normalized is None:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def get_valid_int(prompt, min_value=None):
    """Keep asking until the user provides a valid whole number, optionally
    enforcing a minimum. Accepts extra text/symbols and thousands
    separators, e.g. '1,000 units' -> 1000."""
    while True:
        raw = ask(prompt).strip()
        value = parse_int(raw)
        if value is None:
            print("Please enter a valid whole number (e.g. 10 or 1,000), or 'exit' to cancel.")
            continue
        if min_value is not None and value < min_value:
            print(f"Please enter a number of at least {min_value:,}.")
            continue
        return value


def get_valid_price(prompt):
    """Keep asking until the user provides a valid price.
    Accepts currency symbols/text and thousands separators, e.g. '1,800$ each' -> 1800.0."""
    while True:
        raw = ask(prompt).strip()
        value = parse_price(raw)
        if value is None:
            print("Please enter a valid price (e.g. 1800 or 1,800.00), or 'exit' to cancel.")
            continue
        return value


def get_currency(prompt, default=DEFAULT_CURRENCY):
    """Ask for a currency symbol/code, falling back to a default if left blank."""
    raw = ask(prompt).strip()
    return raw if raw else default


def format_price(details):
    """Format a product's price with its own currency and thousands separators."""
    return f"{details['currency']}{details['price']:,.2f}"


def format_total(details):
    """Format a product's total stock value (quantity x price), with
    its own currency and thousands separators."""
    total = details["quantity"] * details["price"]
    return f"{details['currency']}{total:,.2f}"


def find_product(inventory, query):
    """Find a product by partial, case-insensitive name match.
    Returns the matched product name, or None if nothing was found or the
    user cancels. If multiple products match, asks the user to pick one."""
    query = query.strip().lower()
    if not query:
        return None

    matches = [name for name in inventory if query in name.lower()]

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    print(f"\nMultiple products match '{query}':")
    for i, name in enumerate(matches, start=1):
        print(f"  {i}. {name}")
    choice = ask("Enter the number of the product you mean (or leave blank to cancel): ").strip()
    if not choice:
        return None
    if choice.isdigit() and 1 <= int(choice) <= len(matches):
        return matches[int(choice) - 1]
    print("Invalid selection.")
    return None


def add_product(inventory):
    """Add a new product, or update quantity if it already exists.
    Supports 'back' to return to the previous question, and 'exit'/'cancel'
    to abandon the whole thing."""
    values = {}
    step = 0
    total_steps = 4  # name, quantity, currency, price

    while step < total_steps:
        try:
            if step == 0:
                name = ask("Enter product name: ", allow_step_back=False).strip()
                if not name:
                    print("Product name cannot be empty.")
                    continue
                existing_match = next((k for k in inventory if k.lower() == name.lower()), None)
                if existing_match:
                    name = existing_match
                    print(f"'{name}' already exists. Continuing will add to its current stock "
                          f"and overwrite its price/currency.")
                values["name"] = name

            elif step == 1:
                raw = ask("Enter quantity: ", allow_step_back=True).strip()
                quantity = parse_int(raw)
                if quantity is None or quantity < 0:
                    print("Please enter a whole number of zero or more (e.g. 10 or 1,000).")
                    continue
                values["quantity"] = quantity

            elif step == 2:
                raw = ask(
                    f"Enter the currency symbol/code for this product's price "
                    f"(e.g. $, KES, €) [default: {DEFAULT_CURRENCY}]: ",
                    allow_step_back=True,
                ).strip()
                values["currency"] = raw if raw else DEFAULT_CURRENCY

            elif step == 3:
                raw = ask(
                    f"Enter price per unit (in {values['currency']}): ",
                    allow_step_back=True,
                ).strip()
                price = parse_price(raw)
                if price is None or price <= 0:
                    print("Please enter a price greater than zero (e.g. 1800 or 1,800.00).")
                    continue
                values["price"] = price

        except StepBack:
            step -= 1
            continue

        step += 1

    product_name = values["name"]
    quantity = values["quantity"]
    currency = values["currency"]
    price = values["price"]

    if product_name in inventory:
        inventory[product_name]["quantity"] += quantity
        inventory[product_name]["price"] = price
        inventory[product_name]["currency"] = currency
    else:
        inventory[product_name] = {"quantity": quantity, "price": price, "currency": currency}

    print(f"Added: {product_name} | Qty: {quantity} | Price: {format_price(inventory[product_name])}")
    save_data(inventory)


def update_product(inventory):
    """Update the quantity, price, and/or currency of an existing product.
    Supports 'back' to return to the previous question, and 'exit'/'cancel'
    to abandon the whole thing."""
    query = ask("Enter product name to update (a few letters is fine): ").strip()
    product_name = find_product(inventory, query)

    if not product_name:
        print(f"No product matching '{query}' found.")
        return

    current = inventory[product_name]
    print(f"Current: Qty={current['quantity']}, Price={format_price(current)}")

    values = {"quantity_raw": "", "currency": "", "price_raw": ""}
    step = 0
    total_steps = 3  # quantity, currency, price

    while step < total_steps:
        try:
            if step == 0:
                values["quantity_raw"] = ask(
                    "Enter new quantity (leave blank to keep current): ",
                    allow_step_back=False,
                ).strip()

            elif step == 1:
                new_currency = ask(
                    f"Enter new currency symbol/code (leave blank to keep '{current['currency']}'): ",
                    allow_step_back=True,
                ).strip()
                if new_currency and len(new_currency) > 6:
                    print(f"'{new_currency}' doesn't look like a currency symbol/code — it will be left unchanged.")
                    new_currency = ""
                values["currency"] = new_currency

            elif step == 2:
                values["price_raw"] = ask(
                    f"Enter new price in {values['currency'] or current['currency']} "
                    f"(leave blank to keep current): ",
                    allow_step_back=True,
                ).strip()

        except StepBack:
            step -= 1
            continue

        step += 1

    new_quantity = None
    if values["quantity_raw"]:
        parsed_quantity = parse_int(values["quantity_raw"])
        if parsed_quantity is None:
            print("Could not read a valid quantity — it will be left unchanged.")
        elif parsed_quantity < 0:
            print("Quantity cannot be negative — it will be left unchanged.")
        else:
            new_quantity = parsed_quantity

    new_currency = values["currency"]

    new_price = None
    if values["price_raw"]:
        parsed_price = parse_price(values["price_raw"])
        if parsed_price is None:
            print("Could not read a valid price — it will be left unchanged.")
        elif parsed_price <= 0:
            print("Price must be greater than zero — it will be left unchanged.")
        else:
            new_price = parsed_price

    if new_quantity is None and new_price is None and not new_currency:
        print("No changes made.")
        return

    preview_currency = new_currency or current["currency"]
    preview_quantity = new_quantity if new_quantity is not None else current["quantity"]
    preview_price = new_price if new_price is not None else current["price"]

    print(f"\nThis will update '{product_name}' to: "
          f"Qty={preview_quantity:,}, Price={preview_currency}{preview_price:,.2f}")
    confirm = ask("Confirm these changes? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Update cancelled — no changes made.")
        return

    if new_quantity is not None:
        current["quantity"] = new_quantity
    if new_currency:
        current["currency"] = new_currency
    if new_price is not None:
        current["price"] = new_price

    print(f"Updated '{product_name}': Qty={current['quantity']}, Price={format_price(current)}")
    save_data(inventory)


def delete_product(inventory):
    """Delete an existing product from the inventory."""
    query = ask("Enter product name to delete (a few letters is fine): ").strip()
    product_name = find_product(inventory, query)

    if not product_name:
        print(f"No product matching '{query}' found.")
        return

    confirm = ask(f"Are you sure you want to delete '{product_name}'? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Delete cancelled.")
        return

    del inventory[product_name]
    print(f"'{product_name}' has been deleted from inventory.")
    save_data(inventory)


def record_sale(inventory):
    """Record a sale, reducing stock for the given product."""
    query = ask("Enter product name sold (a few letters is fine): ").strip()
    product_name = find_product(inventory, query)

    if not product_name:
        print(f"No product matching '{query}' found.")
        return

    quantity_sold = get_valid_int("Enter quantity sold: ", min_value=1)
    details = inventory[product_name]
    available = details["quantity"]

    if quantity_sold > available:
        print(f"Cannot sell {quantity_sold} units — only {available} in stock.")
        return

    details["quantity"] -= quantity_sold
    total = quantity_sold * details["price"]
    total_display = f"{details['currency']}{total:,.2f}"
    print(f"Sold {quantity_sold} of '{product_name}' for a total of {total_display}. "
          f"Remaining stock: {details['quantity']}")
    save_data(inventory)


def search_product(inventory):
    """Search for products by name (partial match, case-insensitive)."""
    query = ask("Enter product name to search: ").strip().lower()
    matches = {name: details for name, details in inventory.items()
               if query in name.lower()}

    if not matches:
        print(f"No products matching '{query}' found.")
        return

    print(f"\nFound {len(matches)} match(es):")
    for name, details in matches.items():
        print(f"  {name} | Qty: {details['quantity']} | Price: {format_price(details)}")


def check_low_stock(inventory):
    """List all products at or below the low-stock threshold."""
    low_stock = {name: details for name, details in inventory.items()
                 if details["quantity"] <= LOW_STOCK_THRESHOLD}

    if not low_stock:
        print(f"No products are low on stock (threshold: {LOW_STOCK_THRESHOLD}).")
        return

    print(f"\nLow stock items (threshold: {LOW_STOCK_THRESHOLD}):")
    for name, details in low_stock.items():
        print(f"  {name} | Qty: {details['quantity']}")


def view_inventory(inventory):
    """Display the full inventory in a simple table, sorted alphabetically,
    flagging any item at or below the low-stock threshold."""
    if not inventory:
        print("Inventory is empty.")
        return

    print(f"\n{'Product':<20}{'Quantity':<12}{'Price':<16}{'Total':<16}{'Status':<12}")
    print("-" * 76)
    for name, details in sorted(inventory.items()):
        status = "LOW STOCK" if details["quantity"] <= LOW_STOCK_THRESHOLD else ""
        print(f"{name:<20}{details['quantity']:<12}{format_price(details):<16}"
              f"{format_total(details):<16}{status:<12}")


def print_menu():
    print("\n=== Inventory Management ===")
    print("1. Add product")
    print("2. Update product")
    print("3. Record sale")
    print("4. Search products")
    print("5. Check low stock")
    print("6. View inventory")
    print("7. Delete product")
    print("8. Exit")
    print("(You can type 'exit', 'cancel', or 'back' at any prompt to return here.)")


def main():
    inventory = load_data()

    actions = {
        "1": add_product,
        "2": update_product,
        "3": record_sale,
        "4": search_product,
        "5": check_low_stock,
        "6": view_inventory,
        "7": delete_product,
    }

    while True:
        print_menu()
        choice = input("Choose an option (1-8): ").strip()

        if choice == "8":
            save_data(inventory)
            print("Goodbye!")
            break
        elif choice in actions:
            try:
                actions[choice](inventory)
            except BackToMenu:
                print("\nCancelled — back to main menu.")
        else:
            print("Invalid option. Please choose a number from 1 to 8.")


if __name__ == "__main__":
    main()

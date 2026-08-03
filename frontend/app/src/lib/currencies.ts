/** ISO 4217 currency catalog — mirrors apps/fx/currencies.py. Used to render the
 * currency lookup instead of a free-text field. */
export interface CurrencyMeta {
  code: string;
  name: string;
  symbol: string;
  digits: number;
}

export const CURRENCIES: readonly CurrencyMeta[] = [
  { code: "USD", name: "US Dollar", symbol: "$", digits: 2 },
  { code: "EUR", name: "Euro", symbol: "€", digits: 2 },
  { code: "GBP", name: "British Pound", symbol: "£", digits: 2 },
  { code: "JPY", name: "Japanese Yen", symbol: "¥", digits: 0 },
  { code: "CHF", name: "Swiss Franc", symbol: "CHF", digits: 2 },
  { code: "CAD", name: "Canadian Dollar", symbol: "C$", digits: 2 },
  { code: "AUD", name: "Australian Dollar", symbol: "A$", digits: 2 },
  { code: "NZD", name: "New Zealand Dollar", symbol: "NZ$", digits: 2 },
  { code: "CNY", name: "Chinese Yuan", symbol: "¥", digits: 2 },
  { code: "HKD", name: "Hong Kong Dollar", symbol: "HK$", digits: 2 },
  { code: "SGD", name: "Singapore Dollar", symbol: "S$", digits: 2 },
  { code: "INR", name: "Indian Rupee", symbol: "₹", digits: 2 },
  { code: "KES", name: "Kenyan Shilling", symbol: "KSh", digits: 2 },
  { code: "NGN", name: "Nigerian Naira", symbol: "₦", digits: 2 },
  { code: "ZAR", name: "South African Rand", symbol: "R", digits: 2 },
  { code: "GHS", name: "Ghanaian Cedi", symbol: "₵", digits: 2 },
  { code: "UGX", name: "Ugandan Shilling", symbol: "USh", digits: 0 },
  { code: "TZS", name: "Tanzanian Shilling", symbol: "TSh", digits: 2 },
  { code: "EGP", name: "Egyptian Pound", symbol: "E£", digits: 2 },
  { code: "AED", name: "UAE Dirham", symbol: "د.إ", digits: 2 },
  { code: "SAR", name: "Saudi Riyal", symbol: "﷼", digits: 2 },
  { code: "BRL", name: "Brazilian Real", symbol: "R$", digits: 2 },
  { code: "MXN", name: "Mexican Peso", symbol: "$", digits: 2 },
  { code: "ARS", name: "Argentine Peso", symbol: "$", digits: 2 },
  { code: "SEK", name: "Swedish Krona", symbol: "kr", digits: 2 },
  { code: "NOK", name: "Norwegian Krone", symbol: "kr", digits: 2 },
  { code: "DKK", name: "Danish Krone", symbol: "kr", digits: 2 },
  { code: "PLN", name: "Polish Zloty", symbol: "zł", digits: 2 },
  { code: "CZK", name: "Czech Koruna", symbol: "Kč", digits: 2 },
  { code: "TRY", name: "Turkish Lira", symbol: "₺", digits: 2 },
  { code: "KRW", name: "South Korean Won", symbol: "₩", digits: 0 },
  { code: "THB", name: "Thai Baht", symbol: "฿", digits: 2 },
  { code: "IDR", name: "Indonesian Rupiah", symbol: "Rp", digits: 2 },
  { code: "MYR", name: "Malaysian Ringgit", symbol: "RM", digits: 2 },
  { code: "PHP", name: "Philippine Peso", symbol: "₱", digits: 2 },
  { code: "KWD", name: "Kuwaiti Dinar", symbol: "KD", digits: 3 },
  { code: "BHD", name: "Bahraini Dinar", symbol: "BD", digits: 3 },
];

export const CURRENCY_OPTIONS = CURRENCIES.map((c) => ({
  value: c.code,
  label: `${c.code} — ${c.name}`,
}));

/** Date-only values stay in their recorded calendar day, independent of UTC/DST. */
export function dateOnly(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year!, month! - 1, day!, 12);
}

export function calendarDate(value: Date): string {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

export function monthDays(month: string): string[] {
  const first = dateOnly(`${month}-01`);
  first.setDate(first.getDate() - (first.getDay() + 6) % 7);
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(first);
    day.setDate(day.getDate() + index);
    return calendarDate(day);
  });
}

export function shiftMonth(month: string, amount: number): string {
  const day = dateOnly(`${month}-01`);
  day.setMonth(day.getMonth() + amount);
  return calendarDate(day).slice(0, 7);
}

export function saleProfit(price: number, cost: number | null, discount: number, fees: number, shipping: number): number | null {
  if (cost == null || ![price, cost, discount, fees, shipping].every(Number.isFinite)) return null;
  const salePrice = Math.round(price * (1 - discount / 100) * 100 + 1e-8) / 100;
  const profit = salePrice * (1 - fees / 100) - cost - shipping;
  return Math.sign(profit) * Math.round(Math.abs(profit) * 100 + 1e-8) / 100;
}

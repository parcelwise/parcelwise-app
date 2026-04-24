export function Price({ value }: { value: string }) {
  return <span className="price">${Number(value).toFixed(2)}</span>;
}

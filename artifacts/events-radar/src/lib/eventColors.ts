// Hex values required by Leaflet circleMarker API (no CSS var() support).
// Keep in sync with :root in index.css — see comment per entry.
export const TIPO_COLORS: Record<string, string> = {
  convegno: '#0F5E59', // --color-convegno
  corso_formativo: '#2D8A4E', // --color-corso
  fiera_legaltech: '#7B1FA2', // --color-legaltech
  congresso: '#B8860B', // --color-congresso
  webinar: '#4D4D4D', // --color-webinar
  altro: '#9E9E9E', // --color-altro
};

export const TIPO_LABELS: Record<string, string> = {
  convegno: 'Convegno',
  corso_formativo: 'Corso Formativo',
  fiera_legaltech: 'Fiera Legaltech',
  congresso: 'Congresso',
  webinar: 'Webinar',
  altro: 'Altro',
};

export const DEFAULT_COLOR = '#9E9E9E'; // --color-altro

export function getTipoColor(tipo: string): string {
  return TIPO_COLORS[tipo] ?? DEFAULT_COLOR;
}

export const LEGEND_ENTRIES = Object.entries(TIPO_COLORS).map(([tipo, color]) => ({
  tipo,
  color,
  label: TIPO_LABELS[tipo] ?? tipo,
}));

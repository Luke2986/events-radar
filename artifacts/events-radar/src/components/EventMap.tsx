import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import iconUrl from 'leaflet/dist/images/marker-icon.png';
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png';
import shadowUrl from 'leaflet/dist/images/marker-shadow.png';
import type { EventWithOpportunita } from '@workspace/api-client-react';
import { format, parseISO } from 'date-fns';
import { getTipoColor, DEFAULT_COLOR } from '../lib/eventColors';

L.Icon.Default.mergeOptions({ iconUrl, iconRetinaUrl, shadowUrl });

function formatEventDate(iso: string | null | undefined): string {
  return iso ? format(parseISO(iso), 'dd/MM/yyyy') : 'Data da confermare';
}

function buildSinglePopup(event: EventWithOpportunita): HTMLElement {
  const container = document.createElement('div');
  container.style.cssText = 'font-family: var(--font-body); font-size: 13px; min-width: 200px;';

  const title = document.createElement('strong');
  title.style.fontSize = '14px';
  title.textContent = event.titolo;
  container.appendChild(title);

  container.appendChild(document.createElement('br'));
  container.appendChild(document.createTextNode(formatEventDate(event.dataInizio)));

  if (event.organizzatore) {
    container.appendChild(document.createElement('br'));
    container.appendChild(document.createTextNode(event.organizzatore));
  }

  if (event.urlSorgente) {
    container.appendChild(document.createElement('br'));
    container.appendChild(document.createElement('br'));
    const link = document.createElement('a');
    link.href = event.urlSorgente;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.style.cssText = 'color: var(--color-primary); font-weight: 500; text-decoration: none;';
    link.setAttribute('aria-label', 'Vai alla fonte: ' + event.titolo);
    link.textContent = 'Vai alla fonte \u2192';
    container.appendChild(link);
  }

  return container;
}

function buildEventListItem(event: EventWithOpportunita): HTMLElement {
  const item = document.createElement('div');
  item.style.cssText = 'padding: 8px 0; border-bottom: 1px solid rgba(0,0,0,0.08);';

  const title = document.createElement('strong');
  title.style.cssText = 'font-size: 13px; display: block; line-height: 1.3;';
  title.textContent = event.titolo;
  item.appendChild(title);

  const meta = document.createElement('div');
  meta.style.cssText = 'font-size: 12px; color: #555; margin-top: 2px;';
  let metaText = formatEventDate(event.dataInizio);
  if (event.organizzatore) metaText += ' \u2014 ' + event.organizzatore;
  meta.textContent = metaText;
  item.appendChild(meta);

  if (event.urlSorgente) {
    const link = document.createElement('a');
    link.href = event.urlSorgente;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.style.cssText = 'display: inline-block; margin-top: 4px; font-size: 12px; color: var(--color-primary); font-weight: 500; text-decoration: none;';
    link.setAttribute('aria-label', 'Vai alla fonte: ' + event.titolo);
    link.textContent = 'Vai alla fonte \u2192';
    item.appendChild(link);
  }

  return item;
}

function buildCityPopup(city: string, events: EventWithOpportunita[]): HTMLElement {
  const container = document.createElement('div');
  container.style.cssText = 'font-family: var(--font-body); font-size: 13px; min-width: 260px; max-width: 320px;';

  const heading = document.createElement('h4');
  heading.style.cssText = 'margin: 0 0 6px 0; font-size: 14px; font-weight: 600;';
  const eventiLabel = events.length === 1 ? 'evento' : 'eventi';
  heading.textContent = city + ' (' + events.length + ' ' + eventiLabel + ')';
  container.appendChild(heading);

  const list = document.createElement('div');
  list.style.cssText = 'max-height: 240px; overflow-y: auto; padding-right: 4px;';
  events.forEach((event) => list.appendChild(buildEventListItem(event)));
  container.appendChild(list);

  return container;
}

function dominantTipoColor(events: EventWithOpportunita[]): string {
  const counts = new Map<string, number>();
  for (const e of events) {
    counts.set(e.tipoEvento, (counts.get(e.tipoEvento) ?? 0) + 1);
  }
  // Tipi misti → grigio default per segnalare che il gruppo e' eterogeneo
  if (counts.size > 1) return DEFAULT_COLOR;
  const only = counts.keys().next().value;
  return only ? getTipoColor(only) : DEFAULT_COLOR;
}

function makeCityIcon(count: number, color: string): L.DivIcon {
  const size = count >= 10 ? 40 : 34;
  const fontSize = count >= 10 ? 13 : 14;
  const html =
    '<div style="' +
    'width:' + size + 'px;height:' + size + 'px;' +
    'border-radius:50%;' +
    'background:' + color + ';' +
    'border:3px solid var(--color-white);' +
    'box-shadow:0 2px 6px rgba(0,0,0,0.25);' +
    'display:flex;align-items:center;justify-content:center;' +
    'color:var(--color-white);font-family:var(--font-body);' +
    'font-size:' + fontSize + 'px;font-weight:600;' +
    '">' + count + '</div>';
  return L.divIcon({
    html,
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function normalizeCityKey(luogo: string): string {
  return luogo.trim().toLowerCase();
}

function sortByDate(a: EventWithOpportunita, b: EventWithOpportunita): number {
  const ad = a.dataInizio ?? '9999-12-31';
  const bd = b.dataInizio ?? '9999-12-31';
  return ad.localeCompare(bd);
}

type CityGroup = {
  city: string;
  lat: number;
  lng: number;
  events: EventWithOpportunita[];
};

export default function EventMap({ events }: { events: EventWithOpportunita[] }) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerGroupRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current) return;

    if (!mapRef.current) {
      mapRef.current = L.map(mapContainerRef.current).setView([41.9, 12.5], 5);
      // CARTO basemaps now require an API key; OSM tiles are keyless.
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution:
          '&copy; Contributi di <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        maxZoom: 19,
        className: 'map-tiles-muted',
      }).addTo(mapRef.current);

      layerGroupRef.current = L.layerGroup().addTo(mapRef.current);
    }
  }, []);

  useEffect(() => {
    if (!mapRef.current || !layerGroupRef.current) return;

    layerGroupRef.current.clearLayers();

    // Raggruppa gli eventi per citta (chiave = luogo normalizzato).
    // Escludi eventi online ("Online"/"online") e senza coordinate.
    const groups = new Map<string, CityGroup>();
    events.forEach((event) => {
      if (event.lat == null || event.lng == null) return;
      if (!event.luogo) return;
      if (event.luogo === 'Online' || event.luogo === 'online') return;
      const key = normalizeCityKey(event.luogo);
      if (!key) return;
      const existing = groups.get(key);
      if (existing) {
        existing.events.push(event);
      } else {
        groups.set(key, {
          city: event.luogo.trim(),
          lat: event.lat,
          lng: event.lng,
          events: [event],
        });
      }
    });

    groups.forEach((group) => {
      group.events.sort(sortByDate);
      if (group.events.length === 1) {
        const event = group.events[0];
        const color = getTipoColor(event.tipoEvento);
        const marker = L.circleMarker([group.lat, group.lng], {
          radius: 8,
          fillColor: color,
          color: 'white',
          weight: 1.5,
          opacity: 1,
          fillOpacity: 0.9,
        });
        marker.bindPopup(buildSinglePopup(event));
        layerGroupRef.current!.addLayer(marker);
      } else {
        const color = dominantTipoColor(group.events);
        const icon = makeCityIcon(group.events.length, color);
        const marker = L.marker([group.lat, group.lng], { icon });
        marker.bindPopup(buildCityPopup(group.city, group.events));
        layerGroupRef.current!.addLayer(marker);
      }
    });
  }, [events]);

  return <div ref={mapContainerRef} role="region" aria-label="Mappa eventi" style={{ width: '100%', height: '100%' }} />;
}

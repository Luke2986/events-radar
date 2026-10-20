import { pgTable, serial, text, integer, doublePrecision, timestamp, pgEnum, index, unique } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";

// Enums
export const tipoEventoEnum = pgEnum("tipo_evento", [
  "convegno",
  "corso_formativo",
  "fiera_legaltech",
  "congresso",
  "webinar",
  "altro",
]);

export const mercatoEnum = pgEnum("mercato", ["italia", "internazionale"]);

export const statoOpportunitaEnum = pgEnum("stato_opportunita", [
  "non_contattato",
  "contattato",
  "risposto",
  "non_risposto",
  "archiviato",
]);

export const statoScraperEnum = pgEnum("stato_scraper", [
  "attivo",
  "errore",
  "disattivato",
]);

export const tipoFonteEnum = pgEnum("tipo_fonte", [
  "aggregatore",
  "ordine",
  "associazione",
  "legaltech",
  "ente_formativo",
]);

export const scraperSourceEnum = pgEnum("scraper_source", ["manual", "cron"]);

// Tables
export const fonteTable = pgTable("fonte", {
  id: serial("id").primaryKey(),
  nome: text("nome").notNull(),
  urlBase: text("url_base").notNull(),
  tipoFonte: tipoFonteEnum("tipo_fonte").notNull(),
  paese: text("paese").notNull().default("Italia"),
  statoScraper: statoScraperEnum("stato_scraper").notNull().default("attivo"),
  ultimoScrape: timestamp("ultimo_scrape"),
  fallimentiConsecutivi: integer("fallimenti_consecutivi").notNull().default(0),
}, (table) => [
  unique("fonte_nome_key").on(table.nome),
]);

export const eventoTable = pgTable("evento", {
  id: serial("id").primaryKey(),
  titolo: text("titolo").notNull(),
  dataInizio: text("data_inizio"), // stored as ISO date string for flexibility
  dataFine: text("data_fine"),
  luogo: text("luogo"),
  lat: doublePrecision("lat"),
  lng: doublePrecision("lng"),
  tipoEvento: tipoEventoEnum("tipo_evento").notNull().default("altro"),
  organizzatore: text("organizzatore"),
  creditiFormativi: integer("crediti_formativi"),
  urlSorgente: text("url_sorgente"),
  sourceEventUid: text("source_event_uid").notNull(),
  idFonte: integer("id_fonte").references(() => fonteTable.id),
  mercato: mercatoEnum("mercato").notNull().default("italia"),
  dataInserimento: timestamp("data_inserimento").notNull().defaultNow(),
  dataUltimoAggiornamento: timestamp("data_ultimo_aggiornamento").notNull().defaultNow(),
  geocodingAttemptedAt: timestamp("geocoding_attempted_at"),
}, (table) => [
  index("idx_evento_id_fonte").on(table.idFonte),
  index("idx_evento_data_inizio").on(table.dataInizio),
  index("idx_evento_tipo_evento").on(table.tipoEvento),
  index("idx_evento_mercato").on(table.mercato),
  unique("evento_source_event_uid_id_fonte_key").on(table.idFonte, table.sourceEventUid),
]);

export const opportunitaTable = pgTable("opportunita", {
  id: serial("id").primaryKey(),
  idEvento: integer("id_evento")
    .notNull()
    .references(() => eventoTable.id),
  stato: statoOpportunitaEnum("stato").notNull().default("non_contattato"),
  note: text("note"),
  dataUltimoAggiornamento: timestamp("data_ultimo_aggiornamento").notNull().defaultNow(),
}, (table) => [
  unique("opportunita_id_evento_key").on(table.idEvento),
]);

export const scraperRunTable = pgTable("scraper_run", {
  id: serial("id").primaryKey(),
  startedAt: timestamp("started_at").notNull(),
  finishedAt: timestamp("finished_at"),
  source: scraperSourceEnum("source").notNull(),
  inserted: integer("inserted").notNull().default(0),
  updated: integer("updated").notNull().default(0),
  errors: integer("errors").notNull().default(0),
  cleaned: integer("cleaned").notNull().default(0),
  failedFonti: text("failed_fonti").array(),
  fontiProcessed: integer("fonti_processed").notNull().default(0),
  durationS: doublePrecision("duration_s"),
  exitCode: integer("exit_code"),
});

// Insert schemas
export const insertFonteSchema = createInsertSchema(fonteTable).omit({ id: true });
export const insertEventoSchema = createInsertSchema(eventoTable).omit({ id: true });
export const insertOpportunitaSchema = createInsertSchema(opportunitaTable).omit({ id: true });

// Types
export type InsertFonte = z.infer<typeof insertFonteSchema>;
export type Fonte = typeof fonteTable.$inferSelect;
export type InsertEvento = z.infer<typeof insertEventoSchema>;
export type Evento = typeof eventoTable.$inferSelect;
export type InsertOpportunita = z.infer<typeof insertOpportunitaSchema>;
export type Opportunita = typeof opportunitaTable.$inferSelect;

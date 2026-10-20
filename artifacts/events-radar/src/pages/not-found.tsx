import { Card, CardContent } from "@/components/ui/card";

export default function NotFound() {
  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-off-white)" }}>
      <Card style={{ maxWidth: 400, width: "100%", margin: "0 1rem" }}>
        <CardContent style={{ paddingTop: "1.5rem" }}>
          <h1 style={{ fontSize: "1.5rem", fontWeight: "bold", color: "var(--color-primary)" }}>
            404 — Pagina non trovata
          </h1>
          <p style={{ marginTop: "1rem", fontSize: "0.875rem", color: "var(--color-dark-gray)" }}>
            La pagina che cerchi non esiste. Torna alla{" "}
            <a href="/" style={{ color: "var(--color-primary)", textDecoration: "underline" }}>
              dashboard
            </a>
            .
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

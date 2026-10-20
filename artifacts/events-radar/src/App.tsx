import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setBaseUrl } from "@workspace/api-client-react";
import Dashboard from "@/pages/dashboard";

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;
if (apiBaseUrl) {
  setBaseUrl(apiBaseUrl);
}

const queryClient = new QueryClient();

function Router() {
  return (
    <Switch>
      <Route path="/" component={Dashboard} />
      <Route>
        <div style={{ padding: '2rem', textAlign: 'center' }}>
          <h1 className="heading">404 Not Found</h1>
        </div>
      </Route>
    </Switch>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
        <Router />
      </WouterRouter>
    </QueryClientProvider>
  );
}

export default App;

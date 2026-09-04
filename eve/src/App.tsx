import { AssistantRuntimeProvider, useLocalRuntime } from "@assistant-ui/react";
import { Thread } from "./components/Thread";
import { hiroAdapter } from "./runtime/adapter";

export const App = () => {
  const runtime = useLocalRuntime(hiroAdapter);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <main className="app">
        <header className="app-header">
          <h1>eve</h1>
          <p>Baymax, with its tool calls shown as they happen.</p>
        </header>
        <Thread />
      </main>
    </AssistantRuntimeProvider>
  );
};

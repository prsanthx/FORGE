import { useEffect, useState } from "react";
import Shell from "./components/Shell";
import Benchmarks from "./pages/Benchmarks";
import Configs from "./pages/Configs";
import Dashboard from "./pages/Dashboard";
import Providers from "./pages/Providers";
import Repos from "./pages/Repos";
import RunDetail from "./pages/RunDetail";
import Studio from "./pages/Studio";

function useHash(): string {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const onChange = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const route = hash.split("?")[0] || "#/";
  const runMatch = route.match(/^#\/runs\/([^/]+)/);
  let page = <Dashboard onOpen={(id) => (window.location.hash = `#/runs/${id}`)} />;
  if (runMatch) page = <RunDetail id={runMatch[1]} />;
  else if (route === "#/studio" || route === "#/customize") page = <Studio />;
  else if (route === "#/repos") page = <Repos />;
  else if (route === "#/configs") page = <Configs />;
  else if (route === "#/benchmarks") page = <Benchmarks />;
  else if (route === "#/providers" || route === "#/settings") page = <Providers />;
  return <Shell hash={hash}>{page}</Shell>;
}

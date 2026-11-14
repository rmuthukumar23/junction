import { useHashRoute } from "./lib/route";
import { Intro } from "./views/Intro";
import { Runs } from "./views/Runs";
import { RunView } from "./views/RunView";
import { Stats } from "./views/Stats";
import { How } from "./views/How";

export function App() {
  const route = useHashRoute();
  switch (route.view) {
    case "runs": return <Runs />;
    case "run": return <RunView key={route.id} id={route.id} />;
    case "stats": return <Stats />;
    case "how": return <How />;
    default: return <Intro />;
  }
}

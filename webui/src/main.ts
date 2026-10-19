import { createApp } from "vue";
import Home from "./app/page.vue";
import FocusPage from "./app/focus/page.vue";
import AnnotatePage from "./app/annotate/page.vue";
import "./app/globals.css";

const route = window.location.pathname.replace(/\/$/, "");
const App = route === "/generator" ? Home : route === "/focus" ? FocusPage : AnnotatePage;
if (App === AnnotatePage) document.title = "Pixel Review · 拼豆图纠错工作台";

createApp(App).mount("#root");

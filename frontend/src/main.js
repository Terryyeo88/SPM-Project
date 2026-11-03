import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles/tokens.css'
import './styles/base.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
// Rebuild this tab if another tab signs in as someone else (stores/auth.js).
useAuthStore().watchAccountChanges()
app.mount('#app')

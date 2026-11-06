import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({cacheDir:process.env.CATFEEDIK_VITE_CACHE_DIR||'node_modules/.vite',plugins:[react(),tailwindcss()],build:{rollupOptions:{input:{app:'index.html',admin:'admin.html'}}},server:{fs:{deny:['.env','.env.*','*.{crt,pem}','**/.git/**','**/.local/**']},watch:{ignored:['**/artifacts/**','**/.local/**','**/docs/**','**/backend/**']},proxy:{'/api':process.env.CATFEEDIK_API_PROXY||'http://127.0.0.1:8000'}}});

import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({plugins:[react(),tailwindcss()],server:{watch:{ignored:['**/artifacts/**','**/.local/**','**/docs/**','**/backend/**']},proxy:{'/api':'http://127.0.0.1:8000'}}});

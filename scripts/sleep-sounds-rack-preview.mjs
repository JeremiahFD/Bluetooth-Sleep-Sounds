// Task-owned local source preview. All API calls go to disposable simulated data.
import {createServer} from '../frontend/node_modules/vite/dist/node/index.js';
import {fileURLToPath} from 'node:url';
const frontend=fileURLToPath(new URL('../frontend/',import.meta.url));
const server=await createServer({
 root:frontend,configFile:false,base:'/ui/',
 server:{host:'127.0.0.1',port:5173,strictPort:true,
  // Keep the browser's Host/Origin pair intact for backend CSRF validation.
  proxy:{'/api':{target:'http://127.0.0.1:8093',changeOrigin:false},
         '/install':{target:'http://127.0.0.1:8093',changeOrigin:false}}}
});
await server.listen();
process.title='Sleep Sounds rack source preview';
console.log(`SLEEP_SOUNDS_RACK_PREVIEW pid=${process.pid} http://127.0.0.1:5173/ui/#audio`);
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,async()=>{await server.close();process.exit(0)});

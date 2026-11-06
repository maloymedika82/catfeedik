import {useEffect,useRef,useState} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
export type City={id:string;name:string;label:string;country:string;latitude:number;longitude:number;feedings:number};
export function WorldMap({cities,onCity}:{cities:City[];onCity:(city:City)=>void}){
 const element=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),layer=useRef<L.LayerGroup|null>(null),latest=useRef(onCity);
 const [tileError,setTileError]=useState(false);latest.current=onCity;
 useEffect(()=>{const instance=L.map(element.current!,{center:[22,15],zoom:2,minZoom:2,maxZoom:19,scrollWheelZoom:false,worldCopyJump:true});map.current=instance;
 const tiles=L.tileLayer(import.meta.env.VITE_MAP_TILE_URL||'https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'}).addTo(instance);
 tiles.on('tileerror',()=>setTileError(true));tiles.on('tileload',()=>setTileError(false));
 layer.current=L.layerGroup().addTo(instance);const resize=new ResizeObserver(()=>instance.invalidateSize());resize.observe(element.current!);
 return()=>{resize.disconnect();instance.remove();map.current=null;layer.current=null}},[]);
 useEffect(()=>{if(!layer.current)return;layer.current.clearLayers();for(const city of cities){
 const label=document.createElement('span');label.textContent=`${city.label}: ${city.feedings} кормлений`;
 L.circleMarker([city.latitude,city.longitude],{radius:9+Math.min(8,Math.log2(city.feedings+1)),color:'#435d2d',weight:2,fillColor:'#cceaa2',fillOpacity:.95}).bindTooltip(label).on('click',()=>latest.current(city)).addTo(layer.current);
 }},[cities]);
 return <><div className="world-map" ref={element} role="region" aria-label="Интерактивная карта всего мира" tabIndex={0}/>{tileError&&<p role="status" className="map-network-note">Не удалось загрузить часть карты. Проверь интернет; список городов ниже доступен отдельно.</p>}<div className="map-bottom"><span className="dot"/>Мировая карта · только центры городов · <a href="https://www.geonames.org/" target="_blank" rel="noopener noreferrer">GeoNames</a></div>{cities.length?<div className="city-accessible-list" aria-label="Города с кормлениями">{cities.map(c=><button key={c.id} onClick={()=>onCity(c)}>{c.label} <strong>{c.feedings}</strong></button>)}</div>:<p className="rule">Первый город появится после подтверждённого кормления.</p>}</>;
}

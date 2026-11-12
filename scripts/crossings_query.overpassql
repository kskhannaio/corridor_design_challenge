[out:json][timeout:90];
// study stretch: Mahayogi Vemana Rd (100 Ft Rd) carriageways
way(id:111814614,133763768)->.road;
.road out geom;
node(w.road)->.rn;
.rn out;
(
 node["highway"~"crossing|traffic_signals"](12.9236,77.6168,12.9284,77.6220);
 node["crossing"](12.9236,77.6168,12.9284,77.6220);
 node["kerb"](12.9236,77.6168,12.9284,77.6220);
 way["footway"="crossing"](12.9236,77.6168,12.9284,77.6220);
 way["footway"="sidewalk"](12.9236,77.6168,12.9284,77.6220);
 way["highway"~"service|residential|tertiary|footway|living_street"](12.9236,77.6168,12.9284,77.6220);
 way["highway"="construction"](12.9236,77.6168,12.9300,77.6250);
 way["construction"](12.9236,77.6168,12.9300,77.6250);
);
out geom;

[out:json][timeout:90];
(
 nwr["amenity"](12.91907,77.60933,12.93537,77.62660);
 nwr["shop"](12.91907,77.60933,12.93537,77.62660);
 nwr["office"](12.91907,77.60933,12.93537,77.62660);
 nwr["leisure"](12.91907,77.60933,12.93537,77.62660);
 nwr["tourism"](12.91907,77.60933,12.93537,77.62660);
 nwr["healthcare"](12.91907,77.60933,12.93537,77.62660);
 nwr["public_transport"="station"](12.91907,77.60933,12.93537,77.62660);
 nwr["railway"~"station|halt"](12.91907,77.60933,12.93537,77.62660);
 node["highway"="bus_stop"](12.91907,77.60933,12.93537,77.62660);
 nwr["historic"](12.91907,77.60933,12.93537,77.62660);
 nwr["landuse"~"recreation_ground|religious"](12.91907,77.60933,12.93537,77.62660);
 nwr["building"~"school|college|university|hospital|temple|mosque|church|public|government"](12.91907,77.60933,12.93537,77.62660);
);
out center tags;
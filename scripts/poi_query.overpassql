[out:json][timeout:90];
(
 nwr["amenity"](12.91899,77.61238,12.93300,77.62651);
 nwr["shop"](12.91899,77.61238,12.93300,77.62651);
 nwr["office"](12.91899,77.61238,12.93300,77.62651);
 nwr["leisure"](12.91899,77.61238,12.93300,77.62651);
 nwr["tourism"](12.91899,77.61238,12.93300,77.62651);
 nwr["healthcare"](12.91899,77.61238,12.93300,77.62651);
 nwr["public_transport"="station"](12.91899,77.61238,12.93300,77.62651);
 nwr["railway"~"station|halt"](12.91899,77.61238,12.93300,77.62651);
 node["highway"="bus_stop"](12.91899,77.61238,12.93300,77.62651);
 nwr["historic"](12.91899,77.61238,12.93300,77.62651);
 nwr["landuse"~"recreation_ground|religious"](12.91899,77.61238,12.93300,77.62651);
 nwr["building"~"school|college|university|hospital|temple|mosque|church|public|government"](12.91899,77.61238,12.93300,77.62651);
);
out center tags;
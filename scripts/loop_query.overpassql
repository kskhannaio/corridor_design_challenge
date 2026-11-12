[out:json][timeout:120];
// Everything the loop analysis needs, for the A-B-C triangle plus a margin:
// roads with node lists (to assemble each side and find side streets), crossings,
// signals, kerbs, bus stops and the flyover construction.
(
  way["highway"](12.9225,77.6125,12.9320,77.6235);
  node["highway"~"crossing|traffic_signals|bus_stop"](12.9225,77.6125,12.9320,77.6235);
  node["crossing"](12.9225,77.6125,12.9320,77.6235);
  node["kerb"](12.9225,77.6125,12.9320,77.6235);
  node["public_transport"="platform"](12.9225,77.6125,12.9320,77.6235);
  way["construction"](12.9225,77.6125,12.9320,77.6235);
);
out geom;

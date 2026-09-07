# 🎡 FitzLandia

A 3D amusement-park builder for kids. Build roller coasters and water rides piece by piece,
test them against the park's physics rules, then watch guests ride them. Earn money from
tickets, candy stores, toy stores and carnival games, complete challenges, and buy more land.

No install, no build step: it is a single web page (Three.js) that runs in Safari on an iPad.

## Play on an iPad over home wifi

1. On the laptop, open a terminal in this folder and run:

   ```
   python3 serve.py
   ```

   (Python 3 is already on every Mac. On Windows install it from python.org, or run
   `npx serve .` instead.)

2. The terminal prints something like `http://192.168.1.23:8000`.
   On the iPad, connected to the **same wifi**, open Safari and type that address.

3. Optional but recommended: tap **Share → Add to Home Screen** on the iPad.
   The game then opens full screen like an app.

The laptop must stay on and the terminal must stay open while playing.
Progress is saved automatically in the iPad's browser storage.
If the laptop's firewall asks, allow Python to accept incoming connections.

## How the game works

- **🎢 Coaster / 🌊 Water Ride**: tap the grass to place a Station, then tap pieces
  (Chain Lift, Hill Up, Drop, Big Drop, turns, Loop, Corkscrew, Conveyor, Splash Pool). Each piece snaps
  onto the end of the track. **Undo** removes the last one. **Auto-Finish** finds a route
  back to the station.
- **🧪 TEST RIDE**: a car runs the track using real energy rules. If it fails, the game
  says why and marks the spot with a red ring.
- **🏪 Shops**: candy, ice cream, toys, balloons, ring toss, duck pond, carousel, Ferris
  wheel, trees, fountains, flowers. **More Land** grows the park.
- **🏆 Challenges** pay money rewards. Stars come from ride ratings and attractions.
- Camera: one finger spins, two fingers move and zoom, **🎥 Ride Cam** rides in the front seat.

## The physics rules

| Rule | What it means for the builder |
|------|------------------------------|
| Only Chain Lifts and Conveyors add energy | Everything else is gravity |
| Speed comes from height | `v² = v₀² − 2·g·Δh − friction` along the track |
| Hills need speed | You can't climb higher than the tallest hill before it (minus friction) |
| Turns have a speed limit (13) | Too fast on a turn = cars fly off. Add a small hill before it |
| Loops need speed 12, Corkscrews need 9 | Put a big drop right before them or the cars won't make it over |
| Water flows downhill only | Water rides need a Conveyor to go up; Splash Pools sit on the ground |
| Friction never sleeps | Long flat track slowly stops the car |
| Closed loop | The track must come back to the Station |

Rating: bigger drops, more turns, more hills, more speed and longer rides = more stars.

## Files

```
index.html      page + UI
style.css       kid-sized touch UI
js/world.js     renderer, sky, city skyline, park ground, camera controls
js/track.js     track pieces, ride rules, path geometry, vehicles, physics, rating
js/buildings.js shops, games, carousel, Ferris wheel, decorations
js/guests.js    visitors: wander, shop, queue, ride
js/game.js      game state, economy, challenges, save/load, UI
vendor/three.min.js  Three.js r158 (local copy so no internet is needed)
serve.py        LAN web server for the iPad
tools/bundle.py builds a single-file HTML version (dist/fitzlandia.html)
```

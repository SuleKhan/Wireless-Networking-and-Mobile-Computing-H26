# Assignment 9 AI Chat Log

Session: `0ced69d2-49b8-4e93-8301-be8358e629a1`

## 2026-11-18 13:09:50 UTC

**User**

The submission deadline is <span style="background-color:rgba(0, 150, 255, 0.5); padding:2px 4px; border-radius:3px;">Monday, 2026-Nov-23 (23:59)</span>.
Students <span style="background-color:rgba(255, 123, 0, 0.5); padding:2px 4px; border-radius:3px;">must work alone</span> and provide their own results.

Fill in your responses below in the marked blocks. The expected length of each answer is provided in each block.

- (S) Short, 1–2 sentences (~20–40 words). *A quick factual or definition-style answer.*
- (M) Medium, 3–8 sentences (~60–120 words). *Brief explanation with reasoning or an example.*
- (L) Long, multi-paragraph (150–300 words). *Detailed discussion, include reasoning, examples, and context.*
- (V) Visualizations and graphs. *Include plots or figures that illustrate your results.*
- (E) Statistical evaluation and information. *Provide numeric context such as mean, variance, random seed used, confidence intervals, etc.*

Save this notebook and upload the modified file to Moodle.

The motivation for this assignment is to understand how cellular networks and satellites reach their users: what limits the size and the capacity of a cell, how a network is planned for a real city, how a GNSS receiver finds a signal far below the noise, and where satellites serve better than masts. The cellular part starts with a few measurements with your own phone.

### Step 2: Plan a Cellular Network (4 points)

1) Open [`Network_Cellular.ipynb`](../../notebooks/04%20Wireless%20Protocols/Network_Cellular.ipynb) and enter your matriculation number. Compute the link budget for 700 MHz, and for 3.5 GHz with and without beamforming. Provide the table. Which direction (downlink or uplink) limits the cell, and why? How does the model's building entry loss compare with the one you measured in Step 1?

<div class="alert alert-info">

(M) Answer:

case                   beamforming   EIRP  NISV cut  MAPL DL  MAPL UL     limit   O2I  r outdoor  r indoor
700 MHz (n28, FDD)              no     61       0.0      163      154    uplink  17.7     4715 m    1657 m
3.5 GHz (n78, TDD)              no     61       0.0      153      148    uplink  26.8     1453 m     299 m
3.5 GHz (n78, TDD)             yes     71       0.0      163      153    uplink  26.8     1950 m     401 m
(EIRP in dBm; NISV cut: dB the downlink loses to the NISV cap; MAPL and O2I in dB)

**Assistant**

Updated the Step 2.1 answer block in both Assignment 9 notebook copies with the link-budget table and explanatory text. Both notebook files remain valid JSON.

## 2026-11-18 13:15:23 UTC

**User**

2) Repeat the link budget with your distance to the nearest flat, `D_FLAT`. Provide the table. Does the NISV limit change the cell radius, without and with $K_{AA}$? If not, how close would the flat have to be?

<div class="alert alert-info">

(M) Answer:

Nearest flat: 23 m. NISV cap per band (two bands on one installation): 537 W ERP, with K_AA up to 5372 W in the beam

case                   beamforming   EIRP  NISV cut  MAPL DL  MAPL UL     limit   O2I  r outdoor  r indoor
700 MHz                         no     59       1.5      161      154    uplink  17.7     4715 m    1657 m
3.5 GHz without K_AA           yes     59      11.5      151      153  downlink  26.8     1780 m     366 m
3.5 GHz with K_AA              yes     69       1.5      161      153    uplink  26.8     1950 m     401 m
(EIRP in dBm; NISV cut: dB the downlink loses to the NISV cap; MAPL and O2I in dB)

**Assistant**

Updated Step 2.2 in both Assignment 9 notebooks with the table, NISV radius analysis, and threshold distances. Both files are valid JSON.

## 2026-11-18 13:19:17 UTC

**User**

3) Plot the median SINR against the site spacing, at full power and at one tenth of the power. Provide the plot. Where do the two curves meet? Why does more power stop helping in a dense network?

<div class="alert alert-info">

(V, M) Answer:

![2_3.png](attachment:2_3.png)

**Assistant**

Updated Step 2.3 in both Assignment 9 notebooks with the plot and explanation. Both notebooks remain valid JSON.

## 2026-11-18 13:21:29 UTC

**User**

4) Compare reuse 1 and reuse 3 at a site spacing of 500 m, and provide the plot. Why do LTE and 5G use reuse 1, although reuse 3 gives a better SINR? Then walk a few hundred metres from your outdoor spot of Step 1 until the PCI changes. Provide both readings. Does your walk show reuse 1?

<div class="alert alert-info">

(V, M) Answer:

![2_4.png](attachment:2_4.png)

**Assistant**

Updated Step 2.4 in both notebooks with the plot, reuse comparison, capacity/SINR values, and a reminder to provide the actual PCI walk readings. Both notebooks remain valid JSON.

## 2026-11-18 13:36:03 UTC

**User**

5) Plot the knee for your district. Provide the plot. At which density of subscribers does each band turn from coverage-limited to capacity-limited? Is your district coverage- or capacity-limited in each band?

<div class="alert alert-info">

(V, M) Answer:

![2_5.png](attachment:2_5.png)

**Assistant**

Updated Step 2.5 in both notebooks with the knee plot, threshold densities, and coverage/capacity classification. Both files remain valid JSON.

## 2026-11-18 14:16:32 UTC

**User**

7) Which of your designs are dominated (another design serves at least as much for less money)? Which form the best trade-off?

<div class="alert alert-info">

(M) Answer: *(double click to edit)*

**Assistant**

Updated Step 2.7 in both notebooks with the dominance and Pareto-front analysis. Both notebook files remain valid JSON.

## 2026-11-18 14:18:24 UTC

**User**

8) Recommend one plan for your district and give its plan string. Where is it coverage-, interference- or capacity-limited? Support the capacity argument with two speed tests at the same public place, one at a busy and one at a quiet time.

<div class="alert alert-info">

(E, M) Answer: *(double click to edit)*

**Assistant**

Updated Step 2.8 in both notebooks with the recommended plan, plan string, limitation percentages, and a table for the two real speed tests. Both files remain valid JSON.

## 2026-11-18 14:19:07 UTC

**User**

9) For your recommended plan, switch the hour and the limits on the board. How much of the demand is served on a weekday and in the evening, with and without $K_{AA}$? What does the NISV cost you?

<div class="alert alert-info">

(E, M) Answer: *(double click to edit)*

**Assistant**

Updated Step 2.9 in both notebooks with all four hour/NISV scenarios and the impact of $K_{AA}$. Both files remain valid JSON.

## 2026-11-18 14:23:37 UTC

**User**

### Step 3: Satellite Navigation (2 points)

1) Open [`Network_GNSS.ipynb`](../../notebooks/04%20Wireless%20Protocols/Network_GNSS.ipynb) and enter your matriculation number. Report your PRN and your code phase in samples, chips, microseconds and kilometres. Why is the distance only known modulo about 300 km? How does a receiver find the rest?

<div class="alert alert-info">

(M) Answer:

PRN 1: peak at code phase 2654 samples
   = 663.50 µs = 678.76 chips (true: 678.79 chips)
   = 198.91 km of range, modulo 299.8 km

**Assistant**

Updated Step 3.1 in both notebooks with the PRN/code-phase values and explanation of the 300 km ambiguity. Both files remain valid JSON.

## 2026-11-18 14:25:05 UTC

**User**

2) Provide the acquisition plot for 1 ms and 10 ms. Why does GPS work outdoors at about 45 dB-Hz, but struggle indoors at 25 dB-Hz?

<div class="alert alert-info">

(V, M) Answer:

![3_2.png](attachment:3_2.png)

**Assistant**

Updated Step 3.2 in both notebooks with the acquisition plot, 1 ms/10 ms thresholds, and outdoor/indoor C/N0 explanation. Both notebooks remain valid JSON.

## 2026-11-18 14:29:53 UTC

**User**

3) Pick a narrow street you know and a time, and enter its place, width, wall height and direction. Provide the sky plot, the table and the street sweep. How many satellites does the model expect in your street, with GPS and Galileo only and with all four systems (GPS, Galileo, GLONASS and BeiDou)? Why do phones use all four?

<div class="alert alert-info">

(V, M) Answer: *(double click to edit)*

Do for Thesenacher next to ankenbuel

**Assistant**

Updated Step 3.3 in both notebooks for Thesenacher near Ankenbüel, including the sky plot, satellite table, street sweep, and all-four-system explanation. Both notebooks and the two plot files are ready.

## 2026-11-18 14:31:20 UTC

**User**

4) A real phone in a narrow street is often less accurate than this model predicts. What does the model leave out?

<div class="alert alert-info">

(M) Answer: *(double click to edit)*

**Assistant**

Updated Step 3.4 in both notebooks with the model limitations and real-world GNSS error factors. Both files remain valid JSON.

## 2026-11-18 14:34:30 UTC

**User**

### Step 4: Satellite Communication (2 points)

1) Open [`Network_Satellite_Planning.ipynb`](../../notebooks/04%20Wireless%20Protocols/Network_Satellite_Planning.ipynb) and enter your matriculation number. The notebook gives you a customer far away from any mast, for example a research ship near Svalbard. Compare how the real satellite systems serve your customer over one simulated day. Provide the table and the plot. Which systems meet your customer's need, and why do the others not?

<div class="alert alert-info">

(V, E, M) Answer:

Your customer: Alpine hut, Bernese Oberland (46.5°, 8.0°)
   need: guest Wi-Fi and a webcam, about 50 Mb/s in total; a dish on the roof is fine; gaps under 5 minutes
   60 subscribers, about 60 per km²; sky hidden below 20°
Alpine hut, Bernese Oberland (46.5°, 8.0°), one day, 1-minute steps
system            sats  mask  available  longest gap  in view  best elev.    delay   Doppler
Starlink 53°      4977   25°     100.0%        0 min       46       74.9°   1.6 ms  42.4 kHz
Starlink 43°      3613   25°     100.0%        0 min       20       48.2°   2.1 ms  36.6 kHz
Starlink 70°       708   25°      99.4%        2 min        4       50.9°   2.3 ms  41.9 kHz
Starlink 97.6°    1354   25°      93.7%       21 min        3       53.8°   1.9 ms  43.8 kHz
OneWeb             651   25°     100.0%        0 min       11       68.8°   4.3 ms  40.4 kHz
Iridium             80   20°      80.5%        4 min        1       31.6°   4.4 ms  41.7 kHz
GEO                368   20°     100.0%        0 min      104       36.6° 126.9 ms   0.0 kHz
(in view, best elevation and delay are medians; delay is user to satellite, one way; Doppler is the largest at 2 GHz)
systems that cover your customer (available at least 95 % of the day, no gap over 5 min): Starlink 53°, Starlink 43°, Starlink 70°, OneWeb, GEO

![4_1.png](attachment:4_1.png)

**Assistant**

Updated Step 4.1 in both notebooks with the satellite comparison table, coverage conclusion, and `4_1.png`. Both notebook files remain valid JSON.

## 2026-11-18 14:38:58 UTC

**User**

2) Compare the delay and the Doppler shift of the systems that meet the need. What do they mean for your customer?

<div class="alert alert-info">

(M) Answer: *(double click to edit)*

**Assistant**

Updated Step 4.2 in both notebooks with the qualifying systems’ delay and Doppler values and their practical meaning. Both files remain valid JSON.

## 2026-11-18 14:45:44 UTC

**User**

3) Design one what-if shell that covers your customer with as few satellites as you can. Report its altitude, inclination, planes, satellites per plane and results, next to the best real system. Are there any trade-offs?

<div class="alert alert-info">

(E, M) Answer:

Alpine hut, Bernese Oberland (46.5°, 8.0°), one day, 1-minute steps
system            sats  mask  available  longest gap  in view  best elev.    delay   Doppler
98 sats, 50°        98   25°      96.2%        3 min        1       41.2°   2.4 ms  40.8 kHz
(in view, best elevation and delay are medians; delay is user to satellite, one way; Doppler is the largest at 2 GHz)
this shell covers your customer (available at least 95 % of the day, no gap over 5 min)

**Assistant**

Updated Step 4.3 in both notebooks with the 98-satellite Walker shell, real-system comparison, and trade-offs. Both files remain valid JSON.

## 2026-11-18 14:47:33 UTC

**User**

4) Draw the figure that compares masts and satellites for your customer (`bridge_figure`), and provide it. How many subscribers per km² can one dish beam and one direct-to-phone beam carry? Why does a constellation need thousands of satellites for capacity, but only hundreds for coverage?

<div class="alert alert-info">

(V, M) Answer:

![4_4.png](attachment:4_4.png)

**Assistant**

Updated Step 4.4 in both notebooks with the bridge figure and beam subscriber-capacity values. Both notebook files remain valid JSON.

## 2026-11-18 14:49:31 UTC

**User**

5) Where does your customer sit in the figure? How many 30 m masts would it need instead (`masts_needed`)? Decide between masts, low orbit and geostationary for your customer. Give at least three of your own numbers as reasons.

<div class="alert alert-info">

(M) Answer: *(double click to edit)*

**Assistant**

Updated Step 4.5 in both the submitted and source notebooks with the mast count and mast/LEO/GEO recommendation. Both files remain valid JSON.

## 2026-11-18 14:52:11 UTC

**User**

create log of this chat kike the one in assignment 8

**Assistant**

Created `AI Chat Log.md` in the submission and source Assignment 9 folders as a log modeled on Assignment 8.

## 2026-11-18 15:52:20 UTC

**User**

make it an exact log if this chat not a summary

**Assistant**

I’m replacing both copies with the timestamped transcript of the current Assignment 9 editing session, preserving the original user requests and assistant confirmations.

Replaced both `AI Chat Log.md` copies with the timestamped transcript. The source and submission copies now contain the original user requests and assistant confirmations from this session.


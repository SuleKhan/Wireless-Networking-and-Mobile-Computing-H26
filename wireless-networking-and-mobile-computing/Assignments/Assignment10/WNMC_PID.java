package layer2_802Algorithms;

import plot.JEMultiPlotter;
import layer1_802Phy.JE802PhyMode;
import layer2_80211Mac.JE802_11BackoffEntity;
import layer2_80211Mac.JE802_11Mac;
import layer2_80211Mac.JE802_11MacAlgorithm;

/**
 * The algorithm skeleton for course assignment 7, driving the
 * {@code WNMC_Moving_Stations} scenario.
 *
 * <p>Sets its own sampling period, so the sampling interval a student
 * measures with is itself under their control - which is part of the
 * exercise, since too coarse a period hides the behaviour being studied and
 * too fine a one costs simulation time.
 */
public class WNMC_PID extends JE802_11MacAlgorithm {
	
	private JE802_11BackoffEntity theBackoffEntityAC01;
	
	private double theSamplingTime_sec;
	
	public WNMC_PID(String name, JE802_11Mac mac) {
		super(name, mac);
		this.theBackoffEntityAC01 = this.mac.getBackoffEntity(1);
		message("This is station " + this.dot11MACAddress.toString() +". WNMC algorithm: '" + this.algorithmName + "'.", 100);
	}
	
	@SuppressWarnings("unused")
	@Override
	public void compute() {

		this.mac.getMlme().setTheIterationPeriod(0.1);  // the sampling period in seconds, which is the time between consecutive calls of this method "compute()"
		this.theSamplingTime_sec =  this.mac.getMlme().getTheIterationPeriod().getTimeS(); // this sampling time can only be read after the MLME was constructed.
		
		this.theSamplingTime_sec = this.theSamplingTime_sec + 0;
		
		
		// observe outcome:  (might need to be stored from iteration to iteration)
		int aQueueSize = this.theBackoffEntityAC01.getQueueSize();
		int aCurrentQueueSize = this.theBackoffEntityAC01.getCurrentQueueSize();
		double aCurrentTxPower_dBm = this.mac.getPhy().getCurrentTransmitPower_dBm();
		JE802PhyMode aCurrentPhyMode = this.mac.getPhy().getCurrentPhyMode();

		// --------------------- ASSIGNMENT - add your PID controller here:

		// Keep per-controller state between calls without changing the skeleton.
		class PIDState {
			static final java.util.Map<WNMC_PID, PIDState> states = new java.util.WeakHashMap<>();
			double integral;
			double previousError;
			double derivative;
			boolean initialized;
			int modeIndex;
			int samples;
			int previousCollisions;
			boolean failuresInWindow;
			JEMultiPlotter powerPlotter;
		}
		PIDState state = PIDState.states.computeIfAbsent(this, key -> new PIDState());
		String[] modes = {
			"BPSK12", "BPSK34", "QPSK12", "QPSK34",
			"16QAM12", "16QAM34", "64QAM23", "64QAM34"
		};
		double kp = 1.2;
		double ki = 0.3;
		double kd = 0.08;
		double dt = this.theSamplingTime_sec;
		double error = aCurrentQueueSize / (double) aQueueSize - 0.1;
		double slope = state.initialized ? (error - state.previousError) / dt : 0.0;
		state.derivative = 0.8 * state.derivative + 0.2 * slope;
		double candidateIntegral = state.integral + error * dt;
		double candidate = kp * error + ki * candidateIntegral + kd * state.derivative;
		// Anti-windup: only integrate toward the usable output range.
		if ((candidate >= 0.0 && candidate <= 1.0)
				|| (candidate > 1.0 && error < 0.0)
				|| (candidate < 0.0 && error > 0.0)) {
			state.integral = candidateIntegral;
		}
		double demand = Math.max(0.0, Math.min(1.0,
			kp * error + ki * state.integral + kd * state.derivative));
		this.mac.getPhy().setCurrentTransmitPower_dBm(Math.max(-20.0, Math.min(0.0,
			-20.0 + 20.0 * demand)));
		if (state.powerPlotter == null) {
			state.powerPlotter = new JEMultiPlotter("Transmission Power, Station " + this.dot11MACAddress,
				"power", "time [s]", "Transmit power [dBm]",
				this.theUniqueEventScheduler.getEmulationEnd().getTimeMs() / 1000.0, true);
			state.powerPlotter.display();
		}
		state.powerPlotter.plot(this.theUniqueEventScheduler.now().getTimeMs() / 1000.0,
			this.mac.getPhy().getCurrentTransmitPower_dBm(), 0);

		int collisions = this.theBackoffEntityAC01.getTheCollisionCnt();
		state.failuresInWindow |= collisions > state.previousCollisions;
		state.previousCollisions = collisions;
		// Missing ACKs can indicate a weak link in this two-station scenario.
		if (++state.samples >= 10) {
			int desiredMode = (int) Math.round(demand * (modes.length - 1));
			if (state.failuresInWindow) {
				state.modeIndex = Math.max(0, state.modeIndex - 1);
			} else if (state.modeIndex < desiredMode) {
				state.modeIndex++;
			} else if (state.modeIndex > desiredMode) {
				state.modeIndex--;
			}
			state.samples = 0;
			state.failuresInWindow = false;
		}
		this.mac.getPhy().setCurrentPhyMode(modes[state.modeIndex]);
		state.previousError = error;
		state.initialized = true;

		// --------------------- ASSIGNMENT -------------------------------
	}
	
	@Override
	public void plot() {
		if (plotter == null) {
			plotter = new JEMultiPlotter("PID Controller, Station " + this.dot11MACAddress.toString(), "max", "time [s]", "MAC Queue", this.theUniqueEventScheduler.getEmulationEnd().getTimeMs() / 1000.0, true);
			plotter.addSeries("current");
			plotter.display();
		}
		plotter.plot(((Double) theUniqueEventScheduler.now().getTimeMs()).doubleValue() / 1000.0, theBackoffEntityAC01.getQueueSize(), 0);
		plotter.plot(((Double) theUniqueEventScheduler.now().getTimeMs()).doubleValue() / 1000.0, theBackoffEntityAC01.getCurrentQueueSize(), 1);
	}

}

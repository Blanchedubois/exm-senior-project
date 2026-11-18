import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.io.FileWriter;
import java.io.IOException;

public class Node {
    private int T = 1000;
    private double dt = 0.1;
    private double mass = 1.0;

    //node ID where (n = row number, m = column number)
    private int n = 0;
    private int m = 0;

    // If true, this node is under external control (e.g., boundary/pinned)
    private boolean controlledNodes = false;

    /**
     * Constructor that sets initial position and mass, then populates the
     * kinematic list so the first row reflects these initial conditions.
     */
    public Node(double x0, double y0, double mass, int n, int m) {
        // generate default kinematic table
        buildKinematicList();
        // override initial conditions
        setInitialX(x0);
        setInitialY(y0);
        this.mass = mass;
        this.n = n;
        this.m = m;
    }

    /**
     * Constructor that lets the caller specify both the time‑step (dt)
     * and the total simulated time (totalTime).  The number of rows in
     * the kinematic table is automatically set to totalTime / dt.
     */
    public Node(double x0, double y0, double mass,
                int n, int m,
                double dt, double totalTime) {

        this.dt  = dt;
        // compute how many rows we need: include the 0‑th row
        this.T   = (int) Math.round(totalTime / dt);

        buildKinematicList();       // allocate rows
        setInitialX(x0);            // override first row with user values
        setInitialY(y0);

        this.mass = mass;
        this.n = n;
        this.m = m;
    }
    //Tabulates the Kinematics of the Node
    private final List<double[]> kinematicList = new ArrayList<>();

        /**
         * Change the total simulated time.  The table will be rebuilt so
         * that the number of rows equals newTotalTime / dt.
         */
        public void setTotalTime(double newTotalTime) {
            if (newTotalTime <= 0) {
                throw new IllegalArgumentException("totalTime must be positive");
            }
            this.T = (int) Math.round(newTotalTime / dt);
            kinematicList.clear();
            buildKinematicList();
        }

    public void buildKinematicList() {
        double x = 0.0;
        double y = 0.0;
        double vx = 10;
        double vy = 50;
        double ax = 0.0;
        double ay = 0.0;

        // Loop over table rows (not seconds): i < T gives number of rows
        for (int i = 0; i < T; i++) {
            double t = i * dt;
            kinematicList.add(new double[]{t, x, y, vx, vy, ax, ay});
        }
    }



    public void simulateVerlet() {
        for (int i = 0; i < T - 1; i++) {
            double[] current = kinematicList.get(i);       // [t, x, y, vx, vy, ax, ay]
            double[] next = kinematicList.get(i + 1);

            double t = current[0];
            double x = current[1];
            double y = current[2];
            double vx = current[3];
            double vy = current[4];
            double ax = current[5];
            double ay = current[6];

            // Compute next time coordinate
            next[0] = current[0] + dt;

            // Example: constant force (replace with real formula)
            double Fx = 0;
            double Fy = -9.81;

            // Compute new acceleration
            double axNext = Fx/ mass;
            double ayNext = Fy/ mass;

            // Update position using taylor expansion
            double xNext = x + (vx * dt) + (0.5 * ax * Math.pow(dt,2));
            double yNext = y + (vy * dt) + (0.5 * ay * Math.pow(dt,2));

            // Update velocity
            double vxNext = vx + (0.5 * (ax + axNext) * dt);
            double vyNext = vy + (0.5 * (ay + ayNext) * dt);

            // Store in next row
            next[1] = xNext;
            next[2] = yNext;
            next[3] = vxNext;
            next[4] = vyNext;
            next[5] = axNext;
            next[6] = ayNext;
        }
    }

    //Print Kinematics
    public void printKinematics(){
        for (int i = 0; i <= T-1; i++){
            double[] row = kinematicList.get(i);
            System.out.println(Arrays.toString(row));
        }
    }

    //Print Kinematics rounded
    public void printRoundedKinematics(){
        for (int i = 0; i <= T-1; i++){
            double[] row = kinematicList.get(i);

            row[0] = Math.round(row[0]);
            row[1] = Math.round(row[1]);
            row[2] = Math.round(row[2]);
            row[3] = Math.round(row[3]);
            row[4] = Math.round(row[4]);
            row[5] = Math.round(row[5]);
            row[6] = Math.round(row[6]);

            System.out.println(Arrays.toString(row));
        }
    }

    // Export kinematics to table-like string (CSV format)
    public String exportToCSV() {
        StringBuilder sb = new StringBuilder();
        sb.append("t,x,y,vx,vy,ax,ay\n");
        for (double[] row : kinematicList) {
            for (int i = 0; i < row.length; i++) {
                sb.append(row[i]);
                if (i < row.length - 1) {
                    sb.append(",");
                }
            }
            sb.append("\n");
        }
        return sb.toString();
    }

    /**
     * Writes the CSV representation of the kinematics list to a file.
     * If 'path' is null or empty, it defaults to "(n,m)kinematics.csv".
     * @param path the file path to write the CSV to, or null/empty for default
     * @throws IOException if an I/O error occurs
     */
    public void writeCSVToFile(String path) throws IOException {
        String filename = (path == null || path.isEmpty())
            ? "(" + this.n + "," + this.m + ")kinematics.csv"
            : path;
        try (FileWriter writer = new FileWriter(filename)) {
            writer.write(exportToCSV());
        }
    }

    //Getter and Setters:

        //GETTERS:
        public int getN() {
            return n;
        }
        public int getM() {
            return m;
        }
        public int getT() {
            return T;
        }

        public double getDt() {
            return dt;
        }

        public double getMass() {
            return mass;
        }

        //Access a row at a given index
        public double[] getKinematic(double t) {
            int index = (int) Math.round(t / dt);
            double[] original = kinematicList.get(index);
            // Return a copy to prevent external mutation
            return Arrays.copyOf(original, original.length);
        }

        //Gives Position at time t
        public double[] getPosition(double t) {
            int index = (int)Math.round(t / dt);
            double[] row = kinematicList.get(index);  // [t, x, y, vx, vy, ax, ay]
            double[] position = new double[]{row[1], row[2]};  // x and y
            return position;
        }

        //Gives Velocity at time t
        public double[] getVelocity(double t) {
            int index = (int)Math.round(t / dt);
            double[] row = kinematicList.get(index);  // [t, x, y, vx, vy, ax, ay]
            double[] velocity = new double[]{row[3], row[4]};  // vx and vy
            return velocity;
        }

        //Gives Acceleration at time t
        public double[] getAcceleration(double t) {
            int index = (int)Math.round(t / dt);
            double[] row = kinematicList.get(index);  // [t, x, y, vx, vy, ax, ay]
            double[] acceleration = new double[]{row[5], row[6]};  // ax and ay
            return acceleration;
        }
        //Gets Initial X value
        public double getInitialX() {
            double[] current = kinematicList.get(0);       // [t, x, y, vx, vy, ax, ay]
            double x = current[1];
            return x;
        }
        //Gets Initial Y value
        public double getInitialY() {
            double[] current = kinematicList.get(0);       // [t, x, y, vx, vy, ax, ay]
            double y = current[2];
            return y;
        }
        //Gets Initial X-velocity
        public double getInitialVx() {
            double[] current = kinematicList.get(0);       // [t, x, y, vx, vy, ax, ay]
            double vx = current[3];
            return vx;
        }
        //Gets Initial Y-velocity
        public double getInitialVy() {
            double[] current = kinematicList.get(0);       // [t, x, y, vx, vy, ax, ay]
            double vy = current[4];
            return vy;
        }
        //Gets Initial X-acceleration
        public double getInitialAx() {
            double[] current = kinematicList.get(0);       // [t, x, y, vx, vy, ax, ay]
            double ax = current[5];
            return ax;
        }
        //Gets Initial Y-acceleration
        public double getInitialAy() {
            double[] current = kinematicList.get(0);       // [t, x, y, vx, vy, ax, ay]
            double ay = current[6];
            return ay;
        }

    //SETTERS:
        //Sets Position at time t
        public void  setPosition(double t,double x, double y) {
            int index = (int)Math.round(t / dt);
            double[] row = kinematicList.get(index);  // [t, x, y, vx, vy, ax, ay]
            row[1] = x;
            row[2] = y;
        }

        //Sets Velocity at time t
        public void setVelocity(double t,double vx, double vy) {
            int index = (int)Math.round(t / dt);
            double[] row = kinematicList.get(index);  // [t, x, y, vx, vy, ax, ay]
            row[3] = vx;
            row[4] = vy;
        }

        //Sets Acceleration at time t
        public void setAcceleration(double t,double ax, double ay) {
            int index = (int)Math.round(t / dt);
            double[] row = kinematicList.get(index);  // [t, x, y, vx, vy, ax, ay]
            row[5] = ax;
            row[6] = ay;
        }

        //Sets Dt
        public void setDt(double dt) {
            this.dt = dt;
        }
        //Sets M
        public void setMass(double mass) {
                this.mass = mass;
        }
        // Sets the initial X value
        public void setInitialX(double x) {
            double[] row = kinematicList.get(0);
            row[1] = x;
        }

        // Sets the initial Y value
        public void setInitialY(double y) {
            double[] row = kinematicList.get(0);
            row[2] = y;
        }

        // Sets the initial X-velocity
        public void setInitialVx(double vx) {
            double[] row = kinematicList.get(0);
            row[3] = vx;
        }

        // Sets the initial Y-velocity
        public void setInitialVy(double vy) {
            double[] row = kinematicList.get(0);
            row[4] = vy;
        }

        // Sets the initial X-acceleration
        public void setInitialAx(double ax) {
            double[] row = kinematicList.get(0);
            row[5] = ax;
        }

        // Sets the initial Y-acceleration
        public void setInitialAy(double ay) {
            double[] row = kinematicList.get(0);
            row[6] = ay;
        }

}
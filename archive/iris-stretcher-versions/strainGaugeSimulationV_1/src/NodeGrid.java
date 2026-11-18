import java.io.IOException;
import java.io.File;
import java.util.ArrayList;

public class NodeGrid {
    private final int rows, cols;
    private final double dx, dy;
    private final double x0, y0;   // origin of the grid
    private final ArrayList<Node> nodes = new ArrayList<>();
    private String path = "CSV file/" ;

    /** Full constructor with explicit grid origin and user‑defined dt & totalTime */
    public NodeGrid(int rows, int cols,
                    double dx, double dy,
                    double x0, double y0,
                    double mass, double time, double dt) {
        this.rows = rows;
        this.cols = cols;
        this.dx   = dx;
        this.dy   = dy;
        this.x0   = x0;
        this.y0   = y0;
        buildNodes(mass, dt, time);
    }

    //Loop to calculate simulate Verlet for each row and column
    /*
    What this does is it Simulates all particles by cycling through the idx number in the list "nodes".
    It calls the object "p" node in each cell in the list and then calls the method .simulateVerlet()
     */
    public void simulateVerletAll() {
        for (int n = 0; n < rows; n++) {
            for (int m = 0; m < cols; m++) {
                int idx = (n * cols) + m; // gives the id for the particle as a number between 0 and n*m
                Node p = nodes.get(idx);
                p.simulateVerlet();
            }
        }
    }

        //Loop to generate the grid of node objects with n rows and m column
        /*
        Every Node in the nodes list is assigned a number which is its idx.
        This idx number is a number between 0 and n * m where each node has a designated idx number.
        Then the loop constructs a new object p for the node belonging in the idx number (n * cols) + m
        where n is the row number and m is the column number.
        This loop also builds the kinematics list and sets the time T for the simulation.
         */
        private void buildNodes(double mass, double dt, double totalTime) {
            for (int n = 0; n < rows; n++) {
                for (int m = 0; m < cols; m++) {
                    double xPos = x0 + (m * dx);
                    double yPos = y0 + (n * dy);
                    Node p = new Node(xPos, yPos, mass, n, m, dt, totalTime);
                    nodes.add(p);
                }
            }
        }

    public void writeCSVFileAll() throws IOException {
        // Ensure output directory exists
        File dir = new File(path);
        if (!dir.exists()) {
            dir.mkdirs();
        }
        for (int n = 0; n < rows; n++) {
            for (int m = 0; m < cols; m++) {
                int idx = (n * cols) + m;
                Node p = nodes.get(idx);
                // include both folder and filename:
                String out = path + "(" + n + "," + m + ")kinematics.csv";
                p.writeCSVToFile(out);
            }
        }
    }

    // (later) add methods like addSprings(), applyBoundary(), etc.
}
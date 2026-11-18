import javax.swing.JFrame;
import java.io.FileWriter;
import java.io.IOException;

public class Main {
    public static void main(String[] args) throws IOException {

        //testing out first node grid
        int rows = 10;
        int cols = 10;
        double dx = 1;
        double dy = 1;
        double x0 = 0;
        double y0 = 0;
        double mass = 1;
        double time = 10;
        double dt = 0.1;

        NodeGrid grid1 = new NodeGrid(rows, cols, dx, dy, x0, y0, mass, time, dt);
        grid1.simulateVerletAll();
        grid1.writeCSVFileAll();


    }
}


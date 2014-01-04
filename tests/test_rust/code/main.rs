// A simple rust project

static yy: uint = 25u;

mod sub {
    pub mod sub2 {
        pub fn hello() {
            println("hello from a module");
        }

        pub struct nested_struct {
            field2: u32,
        }
    }
}

struct nofields;
struct some_fields {
    field1: u32,
}

fn hello((z, a) : (u32, ~str)) {
    println(yy.to_str());
    let (x, y): (u32, u32) = (5, 3);
    println(x.to_str());
    println(z.to_str());
    let x: u32 = x;
    println(x.to_str());
    let x = ~"hello";
    println(x);
}

fn main() {
    hello((43, ~"a"));
    sub::sub2::hello();

    let s1 = nofields;
    let s2 = some_fields{ field1: 55};
    let s3: some_fields = some_fields{ field1: 55};
    let s4: sub::sub2::nested_struct = sub::sub2::nested_struct{ field2: 55};
}

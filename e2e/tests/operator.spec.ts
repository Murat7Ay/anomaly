import { expect, test, type Page } from "@playwright/test";

async function loginAs(page: Page, name: string) {
  await page.goto("/login");
  await page.getByText(name, { exact: false }).first().click();
  await expect(page.getByRole("heading", { name: "Gelen kutusu" })).toBeVisible();
}

test("analyst triages: inbox → incident → explanation → resolve requires a note", async ({ page }) => {
  await loginAs(page, "Ayşe Yılmaz");
  await expect(page.getByText("Olay kuyruğu")).toBeVisible();
  await expect(page.getByText("İzleme çalışmıyor")).toHaveCount(0); // worker heartbeat is fresh

  const firstP1 = page.locator("tr", { hasText: "P1" }).first();
  await expect(firstP1).toBeVisible();
  await firstP1.getByRole("link").click();

  await expect(page.getByText("Bulgular")).toBeVisible();
  await expect(page.getByText("OPERASYON KONTROL LİSTESİ (KURAL TABANLI)")).toBeVisible();
  await expect(page.getByText("Kayıt sayısı: gözlenen ve beklenen")).toBeVisible();

  await page.getByRole("button", { name: "Karara bağla" }).click();
  await page.getByLabel("Yanlış alarm").check();
  const save = page.getByRole("button", { name: "Kaydet" });
  await expect(save).toBeDisabled(); // a false-alarm verdict must be explained (it drives tuning)
  await page.getByLabel(/Açıklama/).fill("E2E: kurum teyidi");
  await expect(save).toBeEnabled();
  await page.getByRole("button", { name: "Vazgeç" }).click();
});

test("four-eyes: author cannot approve, a different approver can", async ({ page }) => {
  await loginAs(page, "Ayşe Yılmaz");
  await page.getByRole("link", { name: /Onaylar/ }).click();
  await expect(page.getByText("kendi hazırladığınız değişikliği onaylayamazsınız")).toBeVisible();
  await expect(page.getByRole("button", { name: "Onayla" })).toBeDisabled();

  await page.getByRole("button", { name: "çıkış" }).click();
  await loginAs(page, "Mehmet Kaya");
  await page.getByRole("link", { name: /Onaylar/ }).click();
  await expect(page.getByRole("button", { name: "Onayla" })).toBeEnabled();
  await expect(page.getByText("Geriye dönük test", { exact: true })).toBeVisible();
});

test("institution page: contract is readable and a tuning draft can be backtested", async ({ page }) => {
  await loginAs(page, "Ayşe Yılmaz");
  await page.getByRole("link", { name: "Kurumlar" }).click();
  await page.getByText("Orta Anadolu Gaz").click();
  await page.getByRole("tab", { name: "Sözleşme ve kurallar" }).click();
  await expect(page.getByText("Aktif sözleşme v1")).toBeVisible();
  await page.getByRole("button", { name: "Değişiklik taslağı" }).click();
  await page.getByRole("button", { name: /Geriye dönük test/ }).click();
  await expect(page.getByText("Uyarı üreten teslimat")).toBeVisible({ timeout: 30_000 });
});

test("insights show measured quality and the shadow challenger", async ({ page }) => {
  await loginAs(page, "Ayşe Yılmaz");
  await page.getByRole("link", { name: /Model/ }).click();
  await expect(page.getByText("Bulgu türüne göre başarım")).toBeVisible();
  await expect(page.getByText(/Gölge model: mix-shift-v2/)).toBeVisible();
});
